using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Reflection;
using CrusaderDE;
using HarmonyLib;
using R3;
using SHCDESE.API;
using SHCDESE.API.Components.SaveData;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Buildings;
using SHCDESE.EventAPI.MapLoader;
using SHCDESE.EventAPI.Player;
using SHCDESE.Interop;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Isolated fortification lane. The editor may use native-base Visual Beta
    /// variants immediately; gameplay economy, damage, visual recipes, and the
    /// wooden gate remain individually measurement-gated.
    /// </summary>
    internal sealed class FortificationFeature : IExtensionFeature
    {
        private sealed class SelectionContext
        {
            internal FortificationVariantDefinition Variant;
            internal int Mapper;
            internal int RouteIndex;
            internal int PlayerId;
            internal DateTime SelectedAtUtc;
        }

        private readonly struct TileFingerprint : IEquatable<TileFingerprint>
        {
            internal TileFingerprint(
                byte owner,
                byte structureWas,
                byte damage,
                byte defaultHeight,
                int wallGfx,
                byte gatePath)
            {
                Owner = owner;
                StructureWas = structureWas;
                Damage = damage;
                DefaultHeight = defaultHeight;
                WallGfx = wallGfx;
                GatePath = gatePath;
            }

            internal byte Owner { get; }
            internal byte StructureWas { get; }
            internal byte Damage { get; }
            internal byte DefaultHeight { get; }
            internal int WallGfx { get; }
            internal byte GatePath { get; }

            internal bool LooksLikeWall =>
                Owner != 0 && (StructureWas != 0 || WallGfx != 0);

            /// <summary>Editor walls carry no owner (measured 2026-09-02).</summary>
            internal bool HasWallGraphics =>
                StructureWas != 0 || WallGfx != 0;

            public bool Equals(TileFingerprint other)
            {
                return Owner == other.Owner
                    && StructureWas == other.StructureWas
                    && Damage == other.Damage
                    && DefaultHeight == other.DefaultHeight
                    && WallGfx == other.WallGfx
                    && GatePath == other.GatePath;
            }

            public override bool Equals(object value)
            {
                return value is TileFingerprint other && Equals(other);
            }

            public override int GetHashCode()
            {
                unchecked
                {
                    int hash = Owner;
                    hash = (hash * 397) ^ StructureWas;
                    hash = (hash * 397) ^ Damage;
                    hash = (hash * 397) ^ DefaultHeight;
                    hash = (hash * 397) ^ WallGfx;
                    return (hash * 397) ^ GatePath;
                }
            }
        }

        private sealed class WallTransaction
        {
            internal SelectionContext Selection;
            internal Dictionary<int, TileFingerprint> Before;
            internal int PendingTicks;
            internal long SuppressedWood;
            internal long SuppressedStone;
        }

        private static readonly object OwnerGate = new object();
        private static FortificationFeature _activeOwner;

        private readonly object _gate = new object();
        private readonly Harmony _harmony;
        private readonly string _pluginDirectory;
        private readonly Action<string> _info;
        private readonly Action<string> _warning;
        private readonly Action<string> _error;
        private readonly ReadOnlyCollection<ExtensionLeaseClaim> _claims;
        private readonly FortificationSpriteCatalog _spriteCatalog;
        private readonly FortificationVisualRouter _visualRouter;

        private FortificationHudController _hud;
        private FortificationStateStore _state = new FortificationStateStore();
        private FortificationStateStore _pendingLoadedState;
        private string _pendingLoadSha256;
        private SelectionContext _selection;
        private WallTransaction _wallTransaction;
        private IDisposable _mapStartSubscription;
        private IDisposable _mapUnloadSubscription;
        private IDisposable _wallSubscription;
        private IDisposable _resourceSubscription;
        private IDisposable _damageSubscription;
        private MethodInfo _hudSetupTarget;
        private MethodInfo _mapperTarget;
        private MethodInfo _wallFillinTarget;
        private MethodInfo _wallFillinDeleteTarget;
        private MethodInfo _chevronTarget;
        private bool _chevronPatchApplied;
        private MethodInfo _tileGraphicTarget;
        private bool _tileGraphicPatchApplied;
        private bool _hudPatchApplied;
        private bool _mapperPatchApplied;
        private bool _wallFillinPatchApplied;
        private bool _wallFillinDeletePatchApplied;
        private bool _saveHandlerRegistered;
        private bool _prepared;
        private bool _applied;
        private bool _mapActive;
        private bool _editorMode;
        private bool _scopeAllowed;
        private bool _startingOwnedMapper;
        private bool _resourceDebitReentrant;
        private bool _editorReadyObserved;
        private string _failure;

        internal FortificationFeature(
            Harmony harmony,
            string pluginDirectory,
            Action<string> info,
            Action<string> warning,
            Action<string> error)
        {
            _harmony = harmony ?? throw new ArgumentNullException(nameof(harmony));
            _pluginDirectory = pluginDirectory
                ?? throw new ArgumentNullException(nameof(pluginDirectory));
            _info = info ?? throw new ArgumentNullException(nameof(info));
            _warning = warning ?? throw new ArgumentNullException(nameof(warning));
            _error = error ?? throw new ArgumentNullException(nameof(error));
            _spriteCatalog = new FortificationSpriteCatalog(
                pluginDirectory,
                _info,
                _warning);
            _visualRouter = new FortificationVisualRouter(_spriteCatalog, _info);

            var claims = new List<ExtensionLeaseClaim>
            {
                ExtensionLeaseClaim.Mapper(25),
                ExtensionLeaseClaim.Mapper(27),
                ExtensionLeaseClaim.Mapper(46),
                ExtensionLeaseClaim.Mapper(110),
                ExtensionLeaseClaim.Mapper(140),
                ExtensionLeaseClaim.Mapper(141),
                ExtensionLeaseClaim.Mapper(142),
                ExtensionLeaseClaim.Mapper(143),
                ExtensionLeaseClaim.Hook(
                    "CrusaderDE.HUD_Main.SetupNewBuildScreen(int)"),
                ExtensionLeaseClaim.Hook(
                    "EditorDirector.placeBuildingInteraction(Enums.eMappers)"),
                ExtensionLeaseClaim.Hook(
                    "BuildingR3EventHooks.OnBuildWall"),
                ExtensionLeaseClaim.Hook(
                    "GameMap.addUpdateWallFillin(int,int,int,float,int,int)"),
                ExtensionLeaseClaim.Hook(
                    "GameMap.deleteWallFillin(int)"),
                ExtensionLeaseClaim.Hook(
                    "SpriteMapping.setGenericBuildingTileGraphic(GameMapTile,int,int,int)"),
                ExtensionLeaseClaim.Hook(
                    "SpriteMapping.getChevronImage(GameMapTile,int,int)"),
                ExtensionLeaseClaim.UiElement(
                    "Assets/GUI/XAMLResources/HUD_Main.xaml",
                    "EuropeFortificationPanel"),
                ExtensionLeaseClaim.UiElement(
                    "Assets/GUI/XAMLResources/HUD_Main.xaml",
                    "EuropeFortificationWoodenStairs"),
                ExtensionLeaseClaim.UiElement(
                    "Assets/GUI/XAMLResources/HUD_Main.xaml",
                    "EuropeFortificationWoodenPlatform"),
                ExtensionLeaseClaim.UiElement(
                    "Assets/GUI/XAMLResources/HUD_Main.xaml",
                    "EuropeFortificationWoodGatePanel"),
            };
            if (GeneratedFortificationContract.SaveRoundTripMeasured)
            {
                claims.Add(ExtensionLeaseClaim.Hook(
                    "ModSaveDataAPI.StrongholdEuropeDE.Fortifications.v1"));
            }
            _claims = claims.AsReadOnly();
        }

        public string Id => "building.fortifications";

        public IReadOnlyList<ExtensionLeaseClaim> ExclusiveClaims => _claims;

        public bool Prepare(out string failure)
        {
            if (_prepared)
            {
                failure = "fortification feature was already prepared";
                return false;
            }
            try
            {
                if (!GeneratedFortificationContract.Enabled)
                {
                    failure = "generated fortification contract is disabled";
                    return false;
                }
                if (FortificationVariantCatalog.All.Count
                        != GeneratedFortificationContract.RecordCount
                    || FortificationVariantCatalog.CatalogVersion
                        != GeneratedFortificationContract.RecipeVersion)
                {
                    failure = "compiled and generated fortification catalogues differ";
                    return false;
                }
                if (GeneratedFortificationContract.GameplayCostTransactionsMeasured
                    && !GeneratedFortificationContract.ManagedPlacementMeasured)
                {
                    failure = "gameplay costs require a measured managed-placement route";
                    return false;
                }
                if (!GeneratedFortificationContract
                        .HudIncludesFortificationContributor
                    || GeneratedFortificationContract
                            .HudIncludesDockContributor
                        != GeneratedDockPlacementContract.Enabled)
                {
                    failure = "fortification HUD contributor selection differs from runtime features";
                    return false;
                }
                if (GeneratedFortificationContract.WoodenGateMeasured
                    && (!GeneratedFortificationContract
                            .GameplayCostTransactionsMeasured
                        || !GeneratedFortificationContract
                            .CompleteDamageCoverageMeasured
                        || !GeneratedFortificationContract.VisualRecipesMeasured))
                {
                    failure = "wooden gate measurement lacks a complete mechanics recipe";
                    return false;
                }
                if ((GeneratedFortificationContract.WoodenStairsMeasured
                        || GeneratedFortificationContract
                            .WoodenPlatformMeasured)
                    && (!GeneratedFortificationContract
                            .GameplayCostTransactionsMeasured
                        || !GeneratedFortificationContract
                            .ManagedPlacementMeasured
                        || !GeneratedFortificationContract
                            .CompleteDamageCoverageMeasured
                        || !GeneratedFortificationContract
                            .VisualRecipesMeasured
                        || !GeneratedFortificationContract
                            .SaveRoundTripMeasured))
                {
                    failure = "wooden stair/platform promotion lacks a complete mechanics recipe";
                    return false;
                }

                RequireRuntimeFile(
                    "Runtime/fortifications-v1.tsv",
                    GeneratedFortificationContract.CatalogTsvSize,
                    GeneratedFortificationContract.CatalogTsvSha256,
                    "fortification runtime catalogue");
                PinnedXamlOwnershipGuard.Verify(
                    GeneratedFortificationContract.HudLogicalPath,
                    GeneratedFortificationContract.HudBaseRelativePath,
                    GeneratedFortificationContract.HudBaseSize,
                    GeneratedFortificationContract.HudBaseSha256,
                    _pluginDirectory,
                    GeneratedFortificationContract.HudPatchRelativePath,
                    GeneratedFortificationContract.HudPatchSize,
                    GeneratedFortificationContract.HudPatchSha256,
                    requireOwnedPatch: true);
                _spriteCatalog.Prepare();

                _hudSetupTarget = typeof(HUD_Main).GetMethod(
                    "SetupNewBuildScreen",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(int) },
                    null);
                _mapperTarget = typeof(EditorDirector).GetMethod(
                    "placeBuildingInteraction",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(Enums.eMappers) },
                    null);
                // Wall art hook (measured 2026-09-02): every wall tile is one
                // GameMap.addUpdateWallFillin call with an anim_castle image
                // and a height; the router adjusts that call for variant
                // tiles and adds layer sprites through the same API. The
                // delete prefix removes the layers with the tile.
                _wallFillinTarget = typeof(GameMap).GetMethod(
                    "addUpdateWallFillin",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(int), typeof(int), typeof(int), typeof(float), typeof(int), typeof(int) },
                    null);
                _wallFillinDeleteTarget = typeof(GameMap).GetMethod(
                    "deleteWallFillin",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(int) },
                    null);
                // Walkway tiles and their side faces (measured 2026-09-02): the
                // raised wall-top tile is a GM 12 tile image, its faces are
                // tile_walls chevrons. Both are swapped per variant tile.
                _tileGraphicTarget = typeof(SpriteMapping).GetMethod(
                    "setGenericBuildingTileGraphic",
                    BindingFlags.Public | BindingFlags.Static,
                    null,
                    new[] { typeof(GameMapTile), typeof(int), typeof(int), typeof(int) },
                    null);
                _chevronTarget = typeof(SpriteMapping).GetMethod(
                    "getChevronImage",
                    BindingFlags.Public | BindingFlags.Static,
                    null,
                    new[] { typeof(GameMapTile), typeof(int), typeof(int) },
                    null);
                if (_hudSetupTarget == null
                    || _hudSetupTarget.ReturnType != typeof(bool)
                    || _mapperTarget == null
                    || _mapperTarget.ReturnType != typeof(void)
                    || _wallFillinTarget == null
                    || _wallFillinTarget.ReturnType != typeof(void)
                    || _wallFillinDeleteTarget == null
                    || _wallFillinDeleteTarget.ReturnType != typeof(void)
                    || _tileGraphicTarget == null
                    || _tileGraphicTarget.ReturnType != typeof(void)
                    || _chevronTarget == null
                    || _chevronTarget.ReturnType != typeof(UnityEngine.Sprite))
                {
                    failure = "exact HUD/mapper/wall-fillin/tile-graphic/chevron targets are unavailable";
                    return false;
                }
                if (MapLoaderR3EventHooks.OnStartMap.Observable == null
                    || MapLoaderR3EventHooks.OnUnloadMap.Observable == null
                    || BuildingR3EventHooks.OnBuildWall.Observable == null)
                {
                    failure = "required SHCDE-SE 1.44 observables are unavailable";
                    return false;
                }
                _prepared = true;
                failure = null;
                return true;
            }
            catch (Exception exception)
            {
                failure = Describe(exception);
                return false;
            }
        }

        public void Apply()
        {
            if (!_prepared || _applied)
            {
                throw new InvalidOperationException(
                    "Fortification feature is not prepared or is already applied");
            }
            lock (OwnerGate)
            {
                if (_activeOwner != null)
                {
                    throw new InvalidOperationException(
                        "Another fortification feature instance is active");
                }
                _activeOwner = this;
            }

                _hud = new FortificationHudController(this);
                _hud.Activate();
                if (GeneratedFortificationContract.SaveRoundTripMeasured
                    && !ModSaveDataAPI.Instance.RegisterModDataHandler(
                        GeneratedFortificationContract.SaveDataIdentifier,
                        SaveData,
                        LoadData,
                        SaveDataUnload))
                {
                    throw new InvalidOperationException(
                        "Fortification save-data identifier is already registered");
                }
                _saveHandlerRegistered =
                    GeneratedFortificationContract.SaveRoundTripMeasured;

                _mapStartSubscription =
                    ObservableSubscribeExtensions.Subscribe(
                        MapLoaderR3EventHooks.OnStartMap.Observable,
                        OnStartMap);
                _mapUnloadSubscription =
                    ObservableSubscribeExtensions.Subscribe(
                        MapLoaderR3EventHooks.OnUnloadMap.Observable,
                        OnUnloadMap);
                _wallSubscription =
                    ObservableSubscribeExtensions.Subscribe(
                        BuildingR3EventHooks.OnBuildWall.Observable,
                        OnBuildWall);
                if (GeneratedFortificationContract
                    .GameplayCostTransactionsMeasured)
                {
                    _resourceSubscription =
                        ObservableSubscribeExtensions.Subscribe(
                            PlayerR3EventHooks.OnPlayerSubtractResource.Observable,
                            OnPlayerSubtractResource);
                }
                if (GeneratedFortificationContract
                    .CompleteDamageCoverageMeasured)
                {
                    _damageSubscription =
                        ObservableSubscribeExtensions.Subscribe(
                            BuildingR3EventHooks
                                .OnBuildingTileTakeDamage.Observable,
                            OnBuildingTileTakeDamage);
                }

                MethodInfo hudPostfix = typeof(FortificationFeature).GetMethod(
                    nameof(HudSetupPostfix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo mapperPrefix = typeof(FortificationFeature).GetMethod(
                    nameof(MapperSelectionPrefix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo wallFillinPrefix = typeof(FortificationFeature).GetMethod(
                    nameof(WallFillinPrefix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo wallFillinPostfix = typeof(FortificationFeature).GetMethod(
                    nameof(WallFillinPostfix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo wallFillinDeletePrefix = typeof(FortificationFeature).GetMethod(
                    nameof(WallFillinDeletePrefix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo tileGraphicPostfix = typeof(FortificationFeature).GetMethod(
                    nameof(TileGraphicPostfix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                MethodInfo chevronPostfix = typeof(FortificationFeature).GetMethod(
                    nameof(ChevronImagePostfix),
                    BindingFlags.NonPublic | BindingFlags.Static);
                if (hudPostfix == null || mapperPrefix == null
                    || wallFillinPrefix == null || wallFillinPostfix == null
                    || wallFillinDeletePrefix == null || tileGraphicPostfix == null
                    || chevronPostfix == null)
                {
                    throw new MissingMethodException(
                        "Fortification Harmony callbacks are unavailable");
                }
                _harmony.Patch(
                    _hudSetupTarget,
                    postfix: new HarmonyMethod(hudPostfix));
                _hudPatchApplied = true;
                _harmony.Patch(
                    _mapperTarget,
                    prefix: new HarmonyMethod(mapperPrefix));
                _mapperPatchApplied = true;
                _harmony.Patch(
                    _wallFillinTarget,
                    prefix: new HarmonyMethod(wallFillinPrefix),
                    postfix: new HarmonyMethod(wallFillinPostfix));
                _wallFillinPatchApplied = true;
                _harmony.Patch(
                    _wallFillinDeleteTarget,
                    prefix: new HarmonyMethod(wallFillinDeletePrefix));
                _wallFillinDeletePatchApplied = true;
                _harmony.Patch(
                    _tileGraphicTarget,
                    postfix: new HarmonyMethod(tileGraphicPostfix));
                _tileGraphicPatchApplied = true;
                _harmony.Patch(
                    _chevronTarget,
                    postfix: new HarmonyMethod(chevronPostfix));
                _chevronPatchApplied = true;
                try
                {
                    HarmonyLib.Patches patches = Harmony.GetPatchInfo(_wallFillinTarget);
                    _info(
                        "SEDE_RUNTIME_V1|event=fortification_visual|status=hook_patched"
                        + "|target=" + _wallFillinTarget.DeclaringType.FullName
                        + "." + _wallFillinTarget.Name
                        + "|prefixes=" + (patches == null ? -1 : patches.Prefixes.Count)
                        + "|postfixes=" + (patches == null ? -1 : patches.Postfixes.Count)
                        + "|owners=" + (patches == null ? "none" : string.Join(",", patches.Owners)));
                }
                catch (Exception exception)
                {
                    _warning("Fortification wall-fillin patch info unavailable: " + exception.Message);
                }
                _applied = true;

                // Chainloader activation precedes MainViewModel/FatControler
                // readiness. HUD binding is owned by HudSetupPostfix and the
                // guarded editor-ready transition below.
                SafeInfo(
                    "SEDE_RUNTIME_V1|event=fortifications|status=active"
                    // 2026-09-04: gezaehlt statt festgeschrieben - die Zahl
                    // stand als 7 im Text und war nach dem Zuwachs der
                    // Holztreppe falsch, ohne dass irgendetwas rot wurde.
                    + "|catalog=v1|walls="
                    + FortificationVariantCatalog.AdditionalWalls.Count
                        .ToString(CultureInfo.InvariantCulture)
                    + "|native_battlements=preserved"
                    + "|native_stairs=preserved|native_watchtower=preserved"
                    + "|gameplay_costs_measured="
                    + BoolText(GeneratedFortificationContract
                        .GameplayCostTransactionsMeasured)
                    + "|visual_recipes_measured="
                    + BoolText(GeneratedFortificationContract
                        .VisualRecipesMeasured)
                    + "|wooden_gate_measured="
                    + BoolText(GeneratedFortificationContract
                        .WoodenGateMeasured)
                    + "|wooden_stairs_measured="
                    + BoolText(GeneratedFortificationContract
                        .WoodenStairsMeasured)
                    + "|wooden_platform_measured="
                    + BoolText(GeneratedFortificationContract
                        .WoodenPlatformMeasured)
                    + "|save_roundtrip_measured="
                    + BoolText(GeneratedFortificationContract
                        .SaveRoundTripMeasured));
        }

        public void Tick()
        {
            if (_failure != null)
            {
                throw new InvalidOperationException(_failure);
            }
            if (!_applied)
            {
                return;
            }
            try
            {
                ObserveEditorReadyGate();
                if (_wallTransaction != null && _wallTransaction.PendingTicks > 0)
                {
                    // Post phase found no changed tile yet; bounded retry.
                    CompleteWallTransaction();
                }
                ExpireSelectionIfActionChanged();
            }
            catch (Exception exception)
            {
                RecordFailure("tick", exception);
                throw;
            }
        }

        public void RollbackOwned()
        {
            _applied = false;
            _mapActive = false;
            _scopeAllowed = false;
            _editorMode = false;
            _editorReadyObserved = false;
            _selection = null;
            _wallTransaction = null;
            Dispose(ref _damageSubscription);
            Dispose(ref _resourceSubscription);
            Dispose(ref _wallSubscription);
            Dispose(ref _mapUnloadSubscription);
            Dispose(ref _mapStartSubscription);
            if (_saveHandlerRegistered)
            {
                _saveHandlerRegistered = false;
                ModSaveDataAPI.Instance.UnregisterModDataHandler(
                    GeneratedFortificationContract.SaveDataIdentifier);
            }
            if (_chevronPatchApplied && _chevronTarget != null)
            {
                _chevronPatchApplied = false;
                _harmony.Unpatch(
                    _chevronTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_tileGraphicPatchApplied && _tileGraphicTarget != null)
            {
                _tileGraphicPatchApplied = false;
                _harmony.Unpatch(
                    _tileGraphicTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_wallFillinDeletePatchApplied && _wallFillinDeleteTarget != null)
            {
                _wallFillinDeletePatchApplied = false;
                _harmony.Unpatch(
                    _wallFillinDeleteTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
            }
            if (_wallFillinPatchApplied && _wallFillinTarget != null)
            {
                _wallFillinPatchApplied = false;
                _harmony.Unpatch(
                    _wallFillinTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
                _harmony.Unpatch(
                    _wallFillinTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_mapperPatchApplied && _mapperTarget != null)
            {
                _mapperPatchApplied = false;
                _harmony.Unpatch(
                    _mapperTarget,
                    HarmonyPatchType.Prefix,
                    _harmony.Id);
            }
            if (_hudPatchApplied && _hudSetupTarget != null)
            {
                _hudPatchApplied = false;
                _harmony.Unpatch(
                    _hudSetupTarget,
                    HarmonyPatchType.Postfix,
                    _harmony.Id);
            }
            if (_hud != null)
            {
                _hud.RollbackOwned();
                _hud = null;
            }
            _visualRouter.RollbackOwned();
            _state = new FortificationStateStore();
            _pendingLoadedState = null;
            _pendingLoadSha256 = null;
            lock (OwnerGate)
            {
                if (ReferenceEquals(_activeOwner, this))
                {
                    _activeOwner = null;
                }
            }
        }

        internal bool UiScopeAllowed()
        {
            lock (_gate)
            {
                return _applied
                    && _failure == null
                    && _mapActive
                    && _scopeAllowed;
            }
        }

        internal bool WallVariantUiAllowed()
        {
            lock (_gate)
            {
                return UiScopeAllowed()
                    && (_editorMode
                        || (GeneratedFortificationContract
                                .GameplayCostTransactionsMeasured
                            && GeneratedFortificationContract
                                .ManagedPlacementMeasured
                            && GeneratedFortificationContract
                                .CompleteDamageCoverageMeasured));
            }
        }

        internal bool WoodenGateUiAllowed()
        {
            lock (_gate)
            {
                return WallVariantUiAllowed()
                    && GeneratedFortificationContract.WoodenGateMeasured;
            }
        }

        internal bool WoodenPlatformProbeUiAllowed()
        {
            lock (_gate)
            {
                return UiScopeAllowed()
                    && _editorMode
                    && GeneratedFortificationContract.IsolatedCanary
                    && !GeneratedFortificationContract.WoodenPlatformMeasured;
            }
        }

        internal bool TryStartWallVariant(string variantId)
        {
            try
            {
                FortificationVariantDefinition variant =
                    FortificationVariantCatalog.GetRequired(variantId);
                if (variant.Role != FortificationVariantRole.AdditionalWall
                    || !WallVariantUiAllowed())
                {
                    return false;
                }
                return TryStartVariant(variant, routeIndex: 0);
            }
            catch (Exception exception)
            {
                ClearSelectionContext();
                SafeWarning(
                    "Fortification wall selection failed closed: "
                    + Describe(exception));
                return false;
            }
        }

        internal bool TryStartWoodenGate(int routeIndex)
        {
            try
            {
                if (!WoodenGateUiAllowed())
                {
                    return false;
                }
                return TryStartVariant(
                    FortificationVariantCatalog.WoodenGatehouse,
                    routeIndex);
            }
            catch (Exception exception)
            {
                ClearSelectionContext();
                SafeWarning(
                    "Wooden gate selection failed closed: "
                    + Describe(exception));
                return false;
            }
        }

        internal bool TryStartWoodenPlatform()
        {
            ClearSelectionContext();
            try
            {
                if (!WoodenPlatformProbeUiAllowed())
                {
                    return false;
                }
                return TryStartIsolatedNativeMapperCanary(
                    FortificationVariantCatalog.WoodenPlatform,
                    routeIndex: 0);
            }
            catch (Exception exception)
            {
                SafeWarning(
                    "Wooden platform probe selection failed closed: "
                    + Describe(exception));
                return false;
            }
            finally
            {
                ClearSelectionContext();
            }
        }

        private bool TryStartIsolatedNativeMapperCanary(
            FortificationVariantDefinition variant,
            int routeIndex)
        {
            ClearSelectionContext();
            try
            {
                int mapper = variant.MapperRouteForIndex(routeIndex);
                int requiredPage;
                if (variant.Role == FortificationVariantRole.TowerVariant
                    && variant.Id == "wooden_platform"
                    && mapper == 110
                    && WoodenPlatformProbeUiAllowed())
                {
                    requiredPage = 7;
                }
                else
                {
                    throw new InvalidOperationException(
                        "Only the isolated native tower mapper canary is allowed");
                }

                MainViewModel viewModel = MainViewModel.Instance;
                EditorDirector director = EditorDirector.instance;
                if (viewModel == null
                    || director == null
                    || viewModel.buildScreenID != requiredPage
                    || !viewModel.CanPlaceMapper(MapperStructureKey(mapper)))
                {
                    return false;
                }

                director.placeBuildingInteraction((Enums.eMappers)mapper);
                SafeInfo(
                    "SEDE_RUNTIME_V1|event=fortification_selection"
                    + "|variant=" + variant.Id
                    + "|mapper=" + mapper.ToString()
                    + "|editor=true|visual_beta=true");
                return true;
            }
            finally
            {
                // Mapper 110 is native Tower1. The editor canary starts that
                // native action only; it never lends the mapper a
                // fortification placement context. The wooden stairs left this
                // route on 2026-09-04 and are a wall kind now.
                ClearSelectionContext();
            }
        }

        private bool TryStartVariant(
            FortificationVariantDefinition variant,
            int routeIndex)
        {
            ClearSelectionContext();
            if (variant.Role != FortificationVariantRole.AdditionalWall
                && variant.Role != FortificationVariantRole.Gatehouse)
            {
                throw new InvalidOperationException(
                    "Only wall and measured gate variants may own selection context");
            }
            int page = MainViewModel.Instance == null
                ? -1
                : MainViewModel.Instance.buildScreenID;
            if (MainViewModel.Instance == null
                || EditorDirector.instance == null
                || (page != 1
                    && variant.Role == FortificationVariantRole.AdditionalWall)
                || (page != 8
                    && variant.Role == FortificationVariantRole.Gatehouse))
            {
                return false;
            }
            int mapper = variant.MapperRouteForIndex(routeIndex);
            if (!MainViewModel.Instance.CanPlaceMapper(
                    MapperStructureKey(mapper)))
            {
                return false;
            }
            int playerId = EditorDirector.instance.ActivePlayerID;
            FortificationStateStore.ValidatePlayerId(
                playerId,
                nameof(playerId));

            _selection = new SelectionContext
            {
                Variant = variant,
                Mapper = mapper,
                RouteIndex = routeIndex,
                PlayerId = playerId,
                SelectedAtUtc = DateTime.UtcNow,
            };
            _startingOwnedMapper = true;
            try
            {
                EditorDirector.instance.placeBuildingInteraction(
                    (Enums.eMappers)mapper);
            }
            finally
            {
                _startingOwnedMapper = false;
            }
            SafeInfo(
                "SEDE_RUNTIME_V1|event=fortification_selection"
                + "|variant=" + variant.Id
                + "|mapper=" + mapper.ToString()
                + "|editor=" + BoolText(_editorMode)
                + "|visual_beta="
                + BoolText(!GeneratedFortificationContract
                    .VisualRecipesMeasured));
            return true;
        }

        private void ClearSelectionContext()
        {
            _selection = null;
            _wallTransaction = null;
        }

        private int _buildWallEventLines;

        private void LogBuildWallEvent(BuildWallEventArgs value, string phase)
        {
            if (_buildWallEventLines >= 24)
            {
                return;
            }
            _buildWallEventLines++;
            SelectionContext selection = _selection;
            SafeInfo(
                "SEDE_RUNTIME_V1|event=fortification_build_wall"
                + "|phase=" + phase
                + "|player=" + value.PlayerId.ToString()
                + "|wall_type=" + ((int)value.WallType).ToString()
                + "|begin=" + value.TileXBegin.ToString() + "," + value.TileYBegin.ToString()
                + "|end=" + value.TileXEnd.ToString() + "," + value.TileYEnd.ToString()
                + "|max=" + value.BuildWallsMaximum.ToString()
                + "|selection=" + (selection == null ? "none" : selection.Variant.Id)
                + "|selection_mapper=" + (selection == null ? "-" : selection.Mapper.ToString())
                + "|selection_player=" + (selection == null ? "-" : selection.PlayerId.ToString())
                + "|transaction=" + BoolText(_wallTransaction != null)
                + "|applied=" + BoolText(_applied)
                + "|map_active=" + BoolText(_mapActive)
                + "|scope=" + BoolText(_scopeAllowed));
        }

        private static string FingerprintText(TileFingerprint value)
        {
            return value.Owner.ToString()
                + "/" + value.StructureWas.ToString()
                + "/" + value.Damage.ToString()
                + "/" + value.DefaultHeight.ToString()
                + "/" + value.WallGfx.ToString()
                + "/" + value.GatePath.ToString();
        }

        private void OnBuildWall(BuildWallEventArgs value)
        {
            if (value == null)
            {
                return;
            }
            LogBuildWallEvent(value, value.Phase == EventHookPhase.Post ? "post" : "pre");
            if (value.Phase == EventHookPhase.Post)
            {
                try
                {
                    if (!_applied || !_mapActive || !_scopeAllowed)
                    {
                        _wallTransaction = null;
                        return;
                    }
                    CompleteWallTransaction();
                }
                catch (Exception exception)
                {
                    _wallTransaction = null;
                    RecordFailure("wall_transaction", exception);
                }
                return;
            }
            if (value.Phase != EventHookPhase.Pre)
            {
                return;
            }
            if (!_applied || !_mapActive || !_scopeAllowed)
            {
                ClearSelectionContext();
                return;
            }
            try
            {
                BeginWallTransaction(value);
            }
            catch (Exception exception)
            {
                ClearSelectionContext();
                RecordFailure("wall_transaction", exception);
            }
        }

        private void BeginWallTransaction(BuildWallEventArgs value)
        {
            // OnBuildWall has fresh Pre/Post argument objects and no cancellable
            // result in SHCDE-SE 1.44. Consume the one-shot selection before
            // doing any validation or native tile reads, so every Pre outcome
            // (match, mismatch, or exception) leaves no persistent selection.
            SelectionContext selection = _selection;
            _selection = null;
            _wallTransaction = null;
            if (selection == null
                || selection.Variant.Role
                    != FortificationVariantRole.AdditionalWall
                || value.PlayerId != selection.PlayerId
                || (int)value.WallType != selection.Mapper)
            {
                return;
            }
            var before = new Dictionary<int, TileFingerprint>();
            foreach (int tileId in CandidateLineTiles(
                value.TileXBegin,
                value.TileYBegin,
                value.TileXEnd,
                value.TileYEnd))
            {
                before.Add(tileId, ReadFingerprint(tileId));
            }
            _wallTransaction = new WallTransaction
            {
                Selection = selection,
                Before = before,
            };
        }

        private const int MaximumPendingTransactionTicks = 30;

        private void CompleteWallTransaction()
        {
            WallTransaction transaction = _wallTransaction;
            _wallTransaction = null;
            if (transaction == null)
            {
                return;
            }
            var changed = new List<int>();
            int sampled = 0;
            foreach (KeyValuePair<int, TileFingerprint> pair
                in transaction.Before)
            {
                TileFingerprint after = ReadFingerprint(pair.Key);
                bool afterIsWall = _editorMode
                    ? after.HasWallGraphics
                    : (after.Owner == transaction.Selection.PlayerId && after.LooksLikeWall);
                if (sampled < 4 && _buildWallEventLines < 24 && transaction.PendingTicks == 0)
                {
                    sampled++;
                    _buildWallEventLines++;
                    SafeInfo(
                        "SEDE_RUNTIME_V1|event=fortification_build_wall|phase=sample"
                        + "|tile=" + pair.Key.ToString()
                        + "|before=" + FingerprintText(pair.Value)
                        + "|after=" + FingerprintText(after)
                        + "|selection_player=" + transaction.Selection.PlayerId.ToString());
                }
                if (!pair.Value.Equals(after) && afterIsWall)
                {
                    changed.Add(pair.Key);
                }
            }
            if (_buildWallEventLines < 24 && (changed.Count > 0 || transaction.PendingTicks == 0))
            {
                _buildWallEventLines++;
                SafeInfo(
                    "SEDE_RUNTIME_V1|event=fortification_build_wall|phase=complete"
                    + "|candidates=" + transaction.Before.Count.ToString()
                    + "|changed=" + changed.Count.ToString()
                    + "|pending_ticks=" + transaction.PendingTicks.ToString());
            }
            if (changed.Count == 0)
            {
                if (transaction.PendingTicks < MaximumPendingTransactionTicks)
                {
                    // The engine may commit the tiles a tick later; retry.
                    transaction.PendingTicks++;
                    _wallTransaction = transaction;
                }
                else if (_buildWallEventLines < 24)
                {
                    _buildWallEventLines++;
                    SafeInfo(
                        "SEDE_RUNTIME_V1|event=fortification_build_wall|phase=expired"
                        + "|candidates=" + transaction.Before.Count.ToString());
                }
                return;
            }

            if (!_editorMode)
            {
                CompleteGameplayEconomy(transaction, changed.Count);
            }
            foreach (int tileId in changed)
            {
                FortificationTileState existing;
                bool wasWall = _editorMode
                    ? transaction.Before[tileId].HasWallGraphics
                    : transaction.Before[tileId].LooksLikeWall;
                if (_state.TryGetTile(tileId, out existing))
                {
                    // Same-variant overdraw remains a native repair. A different
                    // tag is never converted in place.
                    if (!string.Equals(
                        existing.VariantId,
                        transaction.Selection.Variant.Id,
                        StringComparison.Ordinal))
                    {
                        continue;
                    }
                }
                else if (wasWall)
                {
                    continue;
                }
                else
                {
                    _state.SetTile(new FortificationTileState(
                        tileId,
                        transaction.Selection.Variant.Id,
                        transaction.Selection.PlayerId));
                }
                // The router keeps the tile even without a catalogue so the
                // missing-recipe measurement can name the frames it needs.
                _visualRouter.ApplyTile(
                    tileId,
                    transaction.Selection.Variant);
            }
            SafeInfo(
                "SEDE_RUNTIME_V1|event=fortification_placed"
                + "|variant=" + transaction.Selection.Variant.Id
                + "|changed_tiles=" + changed.Count.ToString()
                + "|editor=" + BoolText(_editorMode));
        }

        private void OnPlayerSubtractResource(
            PlayerSubtractResourceEventArgs value)
        {
            if (value == null
                || value.Phase != EventHookPhase.Pre
                || _resourceDebitReentrant
                || !_mapActive
                || !_scopeAllowed)
            {
                return;
            }
            WallTransaction transaction = _wallTransaction;
            if (transaction == null
                || value.PlayerId != transaction.Selection.PlayerId)
            {
                return;
            }
            if (value.Good == eGoods.STORED_WOOD_PLANKS)
            {
                transaction.SuppressedWood = checked(
                    transaction.SuppressedWood + value.Amount);
                value.SkipOriginalFunction = true;
            }
            else if (value.Good == eGoods.STORED_STONE_BLOCKS)
            {
                transaction.SuppressedStone = checked(
                    transaction.SuppressedStone + value.Amount);
                value.SkipOriginalFunction = true;
            }
        }

        private void CompleteGameplayEconomy(
            WallTransaction transaction,
            int changedTiles)
        {
            if (!GeneratedFortificationContract
                    .GameplayCostTransactionsMeasured
                || !GeneratedFortificationContract.ManagedPlacementMeasured)
            {
                throw new InvalidOperationException(
                    "Gameplay fortification placement reached an unmeasured economy route");
            }
            int playerId = transaction.Selection.PlayerId;
            var goods = new FortificationGoodsBalance(
                GamePlayerManagerAPI.Instance.GetGoodAmount(
                    playerId,
                    eGoods.STORED_WOOD_PLANKS),
                GamePlayerManagerAPI.Instance.GetGoodAmount(
                    playerId,
                    eGoods.STORED_STONE_BLOCKS));
            FortificationPurchaseQuote quote = FortificationEconomy.Quote(
                transaction.Selection.Variant,
                goods,
                _state.GetEconomyCredit(playerId),
                changedTiles,
                FortificationEconomyContext.Gameplay);
            if (!quote.Affordable
                || quote.NativeDebit.WoodGoods > int.MaxValue
                || quote.NativeDebit.StoneGoods > int.MaxValue)
            {
                throw new InvalidOperationException(
                    "Measured placement produced an unaffordable post-placement quote");
            }
            _resourceDebitReentrant = true;
            try
            {
                if (quote.NativeDebit.WoodGoods > 0)
                {
                    GamePlayerManagerAPI.Instance.RemoveGood(
                        playerId,
                        eGoods.STORED_WOOD_PLANKS,
                        checked((int)quote.NativeDebit.WoodGoods));
                }
                if (quote.NativeDebit.StoneGoods > 0)
                {
                    GamePlayerManagerAPI.Instance.RemoveGood(
                        playerId,
                        eGoods.STORED_STONE_BLOCKS,
                        checked((int)quote.NativeDebit.StoneGoods));
                }
            }
            finally
            {
                _resourceDebitReentrant = false;
            }
            _state.CommitPurchaseCredit(playerId, quote);
        }

        private void OnBuildingTileTakeDamage(
            BuildingTileTakeDamageEventArgs value)
        {
            if (value == null
                || value.Phase != EventHookPhase.Pre
                || !_mapActive
                || !_scopeAllowed
                || !GeneratedFortificationContract
                    .CompleteDamageCoverageMeasured)
            {
                return;
            }
            FortificationTileState state;
            if (_state.TryGetTile(value.TileId, out state))
            {
                FortificationDamageResult result = _state.ScaleTileDamage(
                    value.TileId,
                    value.Damage);
                value.Damage = result.ScaledDamage;
            }
        }

        private void OnStartMap(MapStartEventArgs value)
        {
            if (value == null || value.Phase != EventHookPhase.Post)
            {
                return;
            }
            try
            {
                ActivateMap(editorMode: false);
            }
            catch (Exception exception)
            {
                RecordFailure("map_start", exception);
            }
        }

        private void OnUnloadMap(MapUnloadEventArgs value)
        {
            if (value == null || value.Phase != EventHookPhase.Pre)
            {
                return;
            }
            ClearMapState();
        }

        private void ObserveEditorReadyGate()
        {
            // MainViewModel.Instance constructs the singleton on demand. In
            // SHCDE 2.7 that constructor dereferences FatControler.instance,
            // which is still null during early Chainloader ticks.
            if (!MainViewModel.viewModelLoaded)
            {
                if (_editorReadyObserved)
                {
                    _editorReadyObserved = false;
                    ClearMapState();
                }
                return;
            }
            MainViewModel viewModel = MainViewModel.Instance;
            bool editorReady = viewModel != null
                && viewModel.IsMapEditorMode
                && EditorDirector.instance != null
                && GamePlayerManagerAPI.Instance.IsInMapEditor();
            if (editorReady && !_editorReadyObserved)
            {
                _editorReadyObserved = true;
                ActivateMap(editorMode: true);
            }
            else if (!editorReady && _editorReadyObserved)
            {
                _editorReadyObserved = false;
                ClearMapState();
            }
        }

        private void ActivateMap(bool editorMode)
        {
            bool allowed = DetermineScopeAllowed();
            MainViewModel viewModel = MainViewModel.viewModelLoaded
                ? MainViewModel.Instance
                : null;
            lock (_gate)
            {
                _mapActive = true;
                _editorMode = editorMode
                    || (viewModel != null && viewModel.IsMapEditorMode);
                _scopeAllowed = allowed;
                _selection = null;
                _wallTransaction = null;
                _state = allowed
                    ? FilterLoadedState(_pendingLoadedState)
                    : new FortificationStateStore();
                _pendingLoadedState = null;
                _pendingLoadSha256 = null;
            }
            if (_hud != null && viewModel != null)
            {
                _hud.RebindAndLayout(viewModel.HUDmain);
            }
            SafeInfo(
                "SEDE_RUNTIME_V1|event=fortification_map_scope"
                + "|status=" + (allowed ? "active" : "suppressed")
                + "|editor=" + BoolText(_editorMode));
        }

        private void ClearMapState()
        {
            lock (_gate)
            {
                _mapActive = false;
                _editorMode = false;
                _scopeAllowed = false;
                _selection = null;
                _wallTransaction = null;
                _state = new FortificationStateStore();
            }
            _visualRouter.ClearTiles();
            if (_hud != null)
            {
                _hud.RefreshCurrentPage();
            }
        }

        private byte[] SaveData(SaveContext context)
        {
            try
            {
                if (context == null || !_mapActive || !_scopeAllowed)
                {
                    return null;
                }
                ReconcileStateWithNativeMap();
                return FortificationSaveCodec.Serialize(_state);
            }
            catch (Exception exception)
            {
                SafeError(
                    "Fortification save failed closed: " + Describe(exception));
                return null;
            }
        }

        private void LoadData(byte[] data, LoadContext context)
        {
            try
            {
                if (data == null
                    || data.Length == 0
                    || data.Length > FortificationSaveCodec.MaximumPayloadBytes)
                {
                    throw new InvalidDataException(
                        "Fortification load payload size is invalid");
                }
                string digest = Hashing.Sha256(data);
                if (string.Equals(
                    digest,
                    _pendingLoadSha256,
                    StringComparison.Ordinal))
                {
                    return;
                }
                _pendingLoadedState = FortificationSaveCodec.Deserialize(
                    (byte[])data.Clone());
                _pendingLoadSha256 = digest;
            }
            catch (Exception exception)
            {
                _pendingLoadedState = null;
                _pendingLoadSha256 = null;
                SafeWarning(
                    "Fortification load data was discarded: "
                    + Describe(exception));
            }
        }

        private void SaveDataUnload()
        {
            ClearMapState();
        }

        private FortificationStateStore FilterLoadedState(
            FortificationStateStore loaded)
        {
            var filtered = new FortificationStateStore();
            if (loaded == null)
            {
                return filtered;
            }
            CopyCredits(loaded, filtered);
            foreach (FortificationTileState tile in loaded.SnapshotTiles())
            {
                if (TileMatchesNativeWall(tile.TileId, tile.OwnerPlayerId))
                {
                    filtered.AddTile(tile);
                }
            }
            if (GeneratedFortificationContract.WoodenGateMeasured)
            {
                foreach (FortificationGateState gate in loaded.SnapshotGates())
                {
                    bool valid = true;
                    foreach (int tileId in gate.OccupiedTileIds)
                    {
                        if (!TileMatchesNativeWall(
                            tileId,
                            gate.OwnerPlayerId))
                        {
                            valid = false;
                            break;
                        }
                    }
                    if (valid)
                    {
                        filtered.AddGate(gate);
                    }
                }
            }
            return filtered;
        }

        private void ReconcileStateWithNativeMap()
        {
            var reconciled = new FortificationStateStore();
            CopyCredits(_state, reconciled);
            foreach (FortificationTileState tile in _state.SnapshotTiles())
            {
                if (TileMatchesNativeWall(tile.TileId, tile.OwnerPlayerId))
                {
                    reconciled.AddTile(tile);
                }
            }
            if (GeneratedFortificationContract.WoodenGateMeasured)
            {
                foreach (FortificationGateState gate in _state.SnapshotGates())
                {
                    bool valid = true;
                    foreach (int tileId in gate.OccupiedTileIds)
                    {
                        if (!TileMatchesNativeWall(
                            tileId,
                            gate.OwnerPlayerId))
                        {
                            valid = false;
                            break;
                        }
                    }
                    if (valid)
                    {
                        reconciled.AddGate(gate);
                    }
                }
            }
            _state = reconciled;
            _visualRouter.Sync(_state.SnapshotTiles());
        }

        private static void CopyCredits(
            FortificationStateStore source,
            FortificationStateStore destination)
        {
            for (int player = FortificationStateStore.MinimumPlayerId;
                player <= FortificationStateStore.MaximumPlayerId;
                player++)
            {
                destination.SetEconomyCredit(
                    player,
                    source.GetEconomyCredit(player));
            }
        }

        private static bool TileMatchesNativeWall(int tileId, int owner)
        {
            if (!FortificationStateStore.IsValidTileId(tileId))
            {
                return false;
            }
            try
            {
                TileFingerprint value = ReadFingerprint(tileId);
                return value.Owner == owner && value.LooksLikeWall;
            }
            catch
            {
                return false;
            }
        }

        private void ExpireSelectionIfActionChanged()
        {
            SelectionContext selection = _selection;
            if (selection == null && _wallTransaction != null)
            {
                selection = _wallTransaction.Selection;
            }
            if (selection == null)
            {
                return;
            }
            MainControls controls = MainControls.instance;
            if (controls == null
                || controls.CurrentAction != 5
                || controls.CurrentSubAction != selection.Mapper
                || DateTime.UtcNow - selection.SelectedAtUtc
                    > TimeSpan.FromMinutes(2.0))
            {
                _selection = null;
                _wallTransaction = null;
            }
        }

        private void ObserveMapperSelection(int mapper)
        {
            if (!_startingOwnedMapper
                || _selection == null
                || _selection.Mapper != mapper)
            {
                _selection = null;
                _wallTransaction = null;
            }
        }

        private static void HudSetupPostfix(
            HUD_Main __instance,
            int newScreenID,
            bool __result)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._selection = null;
                owner._wallTransaction = null;
                owner._hud.RebindAndLayout(__instance);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("hud_setup_postfix", exception);
            }
        }

        private static void WallFillinPrefix(
            int _objectID,
            int x,
            int y,
            ref float heightAboveGround,
            ref int image,
            ref int xoffset)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._visualRouter.OnWallFillinPrefix(
                    _objectID, x, y, ref heightAboveGround, ref image, ref xoffset);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("wall_fillin_prefix", exception);
            }
        }

        private static void WallFillinPostfix(int _objectID, int x, int y)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._visualRouter.OnWallFillinPostfix(_objectID, x, y);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("wall_fillin_postfix", exception);
            }
        }

        private static void TileGraphicPostfix(GameMapTile tile, int file, int image)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._visualRouter.OnTileGraphic(tile, file, image);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("tile_graphic_postfix", exception);
            }
        }

        private static void ChevronImagePostfix(
            GameMapTile tile,
            int file,
            int image,
            ref UnityEngine.Sprite __result)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._visualRouter.OnChevronImage(tile, file, image, ref __result);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("chevron_postfix", exception);
            }
        }

        private static void WallFillinDeletePrefix(int objectID)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner == null || !owner._applied)
            {
                return;
            }
            try
            {
                owner._visualRouter.OnWallFillinDeletePrefix(objectID);
            }
            catch (Exception exception)
            {
                owner.RecordFailure("wall_fillin_delete_prefix", exception);
            }
        }

        private static void MapperSelectionPrefix(Enums.eMappers __0)
        {
            FortificationFeature owner = ActiveOwner();
            if (owner != null && owner._applied)
            {
                owner.ObserveMapperSelection((int)__0);
            }
        }

        private static FortificationFeature ActiveOwner()
        {
            lock (OwnerGate)
            {
                return _activeOwner;
            }
        }

        private const int CandidateMargin = 1;
        private const int MaximumCandidateTiles = 40000;

        private static IReadOnlyList<int> CandidateLineTiles(
            int x0,
            int y0,
            int x1,
            int y1)
        {
            int mapSize = GameTileManagerAPI.Instance.GetCurrentMapSize();
            if (mapSize < 1 || mapSize > FortificationStateStore.MapWidth)
            {
                throw new InvalidDataException(
                    "Current fortification map size is invalid");
            }
            GameTileManagerAPI tileApi = GameTileManagerAPI.Instance;
            ValidateCoordinate(tileApi, x0, y0);
            ValidateCoordinate(tileApi, x1, y1);

            // Measured 2026-09-02: the engine walks walls in a zig-zag along
            // the isometric grid, so the drag line itself does not name the
            // tiles. Snapshot the widened bounding box instead; the
            // fingerprint diff picks the tiles the engine really changed.
            // Coordinates are grid coordinates (0..MapWidth-1), not bounded by
            // GetCurrentMapSize (measured 2026-09-02: size below the drag x).
            int limit = FortificationStateStore.MapWidth - 1;
            int minX = Math.Max(0, Math.Min(x0, x1) - CandidateMargin);
            int maxX = Math.Min(limit, Math.Max(x0, x1) + CandidateMargin);
            int minY = Math.Max(0, Math.Min(y0, y1) - CandidateMargin);
            int maxY = Math.Min(limit, Math.Max(y0, y1) + CandidateMargin);
            long area = (long)(maxX - minX + 1) * (maxY - minY + 1);
            if (area > 0 && area <= MaximumCandidateTiles)
            {
                var box = new List<int>((int)area);
                for (int y = minY; y <= maxY; y++)
                {
                    for (int x = minX; x <= maxX; x++)
                    {
                        if (!tileApi.IsTileInsideMapBounds(x, y))
                        {
                            continue;
                        }
                        int boxTileId = tileApi.GetTileId(x, y);
                        if (FortificationStateStore.IsValidTileId(boxTileId))
                        {
                            box.Add(boxTileId);
                        }
                    }
                }
                return box;
            }

            var result = new List<int>();
            int deltaX = Math.Abs(x1 - x0);
            int stepX = x0 < x1 ? 1 : -1;
            int deltaY = -Math.Abs(y1 - y0);
            int stepY = y0 < y1 ? 1 : -1;
            int error = deltaX + deltaY;
            while (true)
            {
                ValidateCoordinate(tileApi, x0, y0);
                int tileId = tileApi.GetTileId(x0, y0);
                FortificationStateStore.ValidateTileId(
                    tileId,
                    nameof(tileId));
                result.Add(tileId);
                if (x0 == x1 && y0 == y1)
                {
                    break;
                }
                int doubled = error * 2;
                if (doubled >= deltaY)
                {
                    error += deltaY;
                    x0 += stepX;
                }
                if (doubled <= deltaX)
                {
                    error += deltaX;
                    y0 += stepY;
                }
                if (result.Count > FortificationStateStore.MapWidth + 1)
                {
                    throw new InvalidDataException(
                        "Fortification wall line exceeds the map bound");
                }
            }
            return result.AsReadOnly();
        }

        private static void ValidateCoordinate(
            GameTileManagerAPI tileApi,
            int x,
            int y)
        {
            if (tileApi == null || !tileApi.IsTileInsideMapBounds(x, y))
            {
                throw new ArgumentOutOfRangeException(
                    "Wall coordinate is outside the current map");
            }
        }

        private static TileFingerprint ReadFingerprint(int tileId)
        {
            GameTileManagerAPI api = GameTileManagerAPI.Instance;
            return new TileFingerprint(
                api.GetTilePlayerOwnerId(tileId),
                api.TileManager.StructureWasGrid[tileId],
                api.GetTileState(tileId),
                api.GetTileDefaultHeight(tileId),
                api.TileManager.WallGFXGrid[tileId],
                api.TileManager.GatePathGrid[tileId]);
        }

        private static bool DetermineScopeAllowed()
        {
            bool networked = GameNetworkAPI.IsNetworkedEnvironment();
            if (!networked)
            {
                return true;
            }

            // SHCDE represents a local skirmish (including loaded saves) as a
            // network environment. Permit that one shape only when the full
            // roster proves exactly one active non-AI member and that member
            // is self. Null/partial/ambiguous rows and every remote human are
            // suppressed without relying on a Steam-id threshold.
            var players = GameNetworkAPI.GetPlayers();
            if (players == null)
            {
                return false;
            }
            int selfHumans = 0;
            foreach (var player in players)
            {
                if (player == null)
                {
                    return false;
                }
                if (player.kicked || player.skirmishAI)
                {
                    continue;
                }
                if (!player.isSelf)
                {
                    return false;
                }
                selfHumans++;
            }
            return selfHumans == 1;
        }

        private static string MapperStructureKey(int mapper)
        {
            switch (mapper)
            {
                case 25:
                    return "STRUCT_STONE_WALL";
                case 26:
                    return "STRUCT_CRENAL_WALL";
                case 27:
                    return "STRUCT_STAIRS";
                case 46:
                    return "STRUCT_WOOD_WALL";
                case 110:
                    return "STRUCT_TOWER1";
                case 140:
                    return "STRUCT_GATE_WOOD1A";
                case 141:
                    return "STRUCT_GATE_WOOD1B";
                case 142:
                    return "STRUCT_GATE_WOOD1C";
                case 143:
                    return "STRUCT_GATE_WOOD1D";
                default:
                    throw new ArgumentOutOfRangeException(nameof(mapper));
            }
        }

        private void RequireRuntimeFile(
            string relativePath,
            long expectedSize,
            string expectedSha256,
            string label)
        {
            string root = Path.GetFullPath(_pluginDirectory).TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
            string path = Path.GetFullPath(Path.Combine(
                root,
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            if (!path.StartsWith(
                root + Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(label + " path escapes the mod root");
            }
            string actual = Hashing.Sha256FileStable(path, expectedSize);
            if (!string.Equals(
                actual,
                expectedSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(label + " SHA-256 mismatch");
            }
        }

        private void RecordFailure(string stage, Exception exception)
        {
            if (_failure != null)
            {
                return;
            }
            _failure = stage + ": " + Describe(exception);
            _scopeAllowed = false;
            _selection = null;
            _wallTransaction = null;
            if (_hud != null)
            {
                try
                {
                    _hud.RollbackOwned();
                }
                catch
                {
                    // The feature host performs the authoritative rollback.
                }
            }
            SafeError(
                "SEDE_RUNTIME_V1|event=fortifications|status=failed"
                + "|stage=" + SanitizeField(stage)
                + "|detail=" + SanitizeField(Describe(exception)));
        }

        private static string Describe(Exception exception)
        {
            return exception == null
                ? "unknown"
                : exception.GetType().Name + ": " + exception.Message;
        }

        private static string BoolText(bool value)
        {
            return value ? "true" : "false";
        }

        private static string SanitizeField(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "unknown";
            }
            string clean = value.Replace('|', ' ')
                .Replace('\r', ' ').Replace('\n', ' ');
            return clean.Length <= 512 ? clean : clean.Substring(0, 512);
        }

        private static void Dispose(ref IDisposable subscription)
        {
            IDisposable owned = subscription;
            subscription = null;
            if (owned != null)
            {
                owned.Dispose();
            }
        }

        private void SafeInfo(string value)
        {
            try { _info(value); } catch { }
        }

        private void SafeWarning(string value)
        {
            try { _warning(value); } catch { }
        }

        private void SafeError(string value)
        {
            try { _error(value); } catch { }
        }
    }
}
