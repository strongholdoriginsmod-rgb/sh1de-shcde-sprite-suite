using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;
using BepInEx;
using CrusaderDE;
using HarmonyLib;
using SHCDESE.API;
using SHCDESE.API.Components.ModManager;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class RosterRuntimeController
    {
        private static readonly string[] TranslationFieldNames =
        {
            "_lookUpTextOverrides",
            "_lookUpTextExOverrides",
            "_tempLookUpTextOverrides",
            "_tempLookUpTextExOverrides"
        };

        private static RosterRuntimeController _current;

        private readonly int _mainThreadId;
        private readonly string _pluginDirectory;
        private readonly Harmony _harmony;
        private readonly Action<string> _logInfo;
        private readonly Action<string> _logWarning;
        private readonly Action<string> _logError;
        private readonly RosterHudGenerationState _hudOwnership =
            new RosterHudGenerationState();

        private RosterRuntimeManifest _manifest;
        private RosterMutationState _mutation;
        private GameTranslateAPI _translateApi;
        private FieldInfo[] _translationFields;
        private IDictionary[] _translationDictionaries;
        private FieldInfo _localizedField;
        private IDictionary _localizedDictionary;
        private IDictionary<string, string> _gameTexts;
        private FieldInfo _mainViewModelInstanceField;
        private FieldInfo _hudMainField;
        private FieldInfo _mainUiLoadedField;
        private string _activeLocale;
        private string _targetTextFullPath;
        private string _hudXamlFullPath;
        private string _hudBuildingsXamlFullPath;
        private bool _prepared;
        private bool _active;
        private bool _failed;
        private bool _restartRequired;
        private bool _cleanupLogged;
        private bool _monitorHealthyLogged;
        private WeakReference _pendingHudInstance;
        private bool _pendingHudLoaded;
        private int _hudGeneration;

        internal RosterRuntimeController(
            string pluginDirectory,
            Harmony harmony,
            Action<string> logInfo,
            Action<string> logWarning,
            Action<string> logError)
        {
            if (string.IsNullOrEmpty(pluginDirectory))
            {
                throw new ArgumentException("Plugin directory is unavailable", nameof(pluginDirectory));
            }
            _pluginDirectory = pluginDirectory;
            _harmony = harmony ?? throw new ArgumentNullException(nameof(harmony));
            _logInfo = logInfo ?? throw new ArgumentNullException(nameof(logInfo));
            _logWarning = logWarning ?? throw new ArgumentNullException(nameof(logWarning));
            _logError = logError ?? throw new ArgumentNullException(nameof(logError));
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
        }

        internal bool Failed
        {
            get { return _failed; }
        }

        internal bool RestartRequired
        {
            get { return _restartRequired; }
        }

        internal void PrepareAndPatch()
        {
            RequireMainThread();
            if (_prepared || !GeneratedRosterContract.Enabled)
            {
                throw new InvalidOperationException(
                    "Roster controller preparation state is not exact");
            }

            string manifestPath = Path.Combine(
                _pluginDirectory,
                "Runtime",
                "unit-roster.tsv");
            _manifest = RosterRuntimeManifest.Load(manifestPath);
            _targetTextFullPath = VerifyPinnedGameFile(
                _manifest.TargetTextRelativePath,
                _manifest.TargetTextSize,
                _manifest.TargetTextSha256,
                "target_text");
            _hudXamlFullPath = VerifyPinnedGameFile(
                _manifest.HudXamlRelativePath,
                _manifest.HudXamlSize,
                _manifest.HudXamlSha256,
                "hud_xaml");
            _hudBuildingsXamlFullPath = VerifyPinnedGameFile(
                _manifest.HudBuildingsXamlRelativePath,
                _manifest.HudBuildingsXamlSize,
                _manifest.HudBuildingsXamlSha256,
                "hud_buildings_xaml");
            VerifyEffectiveXamlAssets();

            if (_current != null && !ReferenceEquals(_current, this))
            {
                throw new InvalidOperationException(
                    "Another roster runtime controller already owns the process");
            }
            _current = this;
            try
            {
                PatchExactLifecycleMethods();
                _prepared = true;
                if (!string.IsNullOrEmpty(FatControler.locale))
                {
                    EnsureActivatedBoundary("startup");
                    if (_failed)
                    {
                        throw new InvalidOperationException(
                            "Roster activation failed at startup");
                    }
                }
            }
            catch
            {
                if (ReferenceEquals(_current, this))
                {
                    _current = null;
                }
                throw;
            }
        }

        internal bool Tick(out string shutdownReason)
        {
            shutdownReason = string.Empty;
            if (_failed)
            {
                shutdownReason = _restartRequired
                    ? "roster restart required"
                    : "roster failed closed";
                return false;
            }
            if (!_active)
            {
                return true;
            }
            try
            {
                RequireMainThread();
                if (VerifyCoreOwnershipBoundary())
                {
                    bool hudReadyForOwnership = ProcessPendingHudBoundary();
                    string ownershipReason;
                    if (hudReadyForOwnership
                        && !VerifyHudOwnership(out ownershipReason))
                    {
                        FailClosed(
                            "hud_ownership_lost",
                            ownershipReason,
                            true);
                    }
                    else if (hudReadyForOwnership
                        && !_monitorHealthyLogged
                        && _hudOwnership.Count == 17)
                    {
                        _monitorHealthyLogged = true;
                        _logInfo(RuntimeLogContract.RosterMonitorHealthy);
                    }
                }
            }
            catch (Exception exception)
            {
                FailClosed("monitor_failed", exception.ToString(), true);
            }
            if (_failed)
            {
                shutdownReason = _restartRequired
                    ? "roster restart required"
                    : "roster failed closed";
                return false;
            }
            return true;
        }

        internal void RollbackOwned(bool applicationQuitting)
        {
            RequireMainThread();
            int restoredEntries = 0;
            int restoredControls = 0;
            object pendingInstance = PendingHudInstance();
            if (pendingInstance != null)
            {
                restoredControls += RestoreUnregisteredHudTags(pendingInstance);
            }
            ClearPendingHudBoundary();
            restoredControls += _hudOwnership.RollbackOwned();
            if (_mutation != null)
            {
                restoredEntries = _mutation.RollbackOwned();
            }
            _active = false;
            if (!_cleanupLogged && (_mutation != null || restoredControls != 0))
            {
                _cleanupLogged = true;
                _logInfo(RuntimeLogContract.RosterCleanup(
                    restoredEntries,
                    restoredControls,
                    applicationQuitting
                        ? "application_quit"
                        : "unexpected_shutdown"));
            }
            if (ReferenceEquals(_current, this))
            {
                _current = null;
            }
        }

        private void PatchExactLifecycleMethods()
        {
            MethodInfo fatAwake = typeof(FatControler).GetMethod(
                "Awake",
                BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly,
                null,
                Type.EmptyTypes,
                null);
            ConstructorInfo hudConstructor = typeof(HUD_Main).GetConstructor(
                BindingFlags.Public | BindingFlags.Instance,
                null,
                Type.EmptyTypes,
                null);
            MethodInfo hudLoaded = typeof(HUD_Main).GetMethod(
                "OnLoadMainUIGrid",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            MethodInfo fatPostfix = typeof(RosterRuntimeController).GetMethod(
                nameof(FatControlerAwakePostfix),
                BindingFlags.NonPublic | BindingFlags.Static);
            MethodInfo hudPrefix = typeof(RosterRuntimeController).GetMethod(
                nameof(HudMainConstructorPrefix),
                BindingFlags.NonPublic | BindingFlags.Static);
            MethodInfo hudPostfix = typeof(RosterRuntimeController).GetMethod(
                nameof(HudMainConstructorPostfix),
                BindingFlags.NonPublic | BindingFlags.Static);
            MethodInfo hudLoadedPostfix = typeof(RosterRuntimeController).GetMethod(
                nameof(HudMainLoadedPostfix),
                BindingFlags.NonPublic | BindingFlags.Static);
            ParameterInfo[] hudLoadedParameters = hudLoaded == null
                ? new ParameterInfo[0]
                : hudLoaded.GetParameters();
            if (fatAwake == null
                || fatAwake.ReturnType != typeof(void)
                || hudConstructor == null
                || hudLoaded == null
                || hudLoaded.ReturnType != typeof(void)
                || hudLoadedParameters.Length != 2
                || hudLoadedParameters[0].ParameterType != typeof(object)
                || !string.Equals(
                    hudLoadedParameters[1].ParameterType.FullName,
                    "Noesis.RoutedEventArgs",
                    StringComparison.Ordinal)
                || fatPostfix == null
                || hudPrefix == null
                || hudPostfix == null
                || hudLoadedPostfix == null)
            {
                throw new MissingMethodException(
                    "Exact roster lifecycle Harmony targets/patches were not found");
            }
            _harmony.Patch(fatAwake, postfix: new HarmonyMethod(fatPostfix));
            _harmony.Patch(
                hudConstructor,
                prefix: new HarmonyMethod(hudPrefix),
                postfix: new HarmonyMethod(hudPostfix));
            _harmony.Patch(
                hudLoaded,
                postfix: new HarmonyMethod(hudLoadedPostfix));
        }

        private static void FatControlerAwakePostfix()
        {
            RosterRuntimeController controller = _current;
            if (controller != null)
            {
                controller.EnsureActivatedBoundary("fat_awake");
                controller.VerifyPreXamlBoundary();
            }
        }

        private static void HudMainConstructorPrefix()
        {
            RosterRuntimeController controller = _current;
            if (controller != null)
            {
                controller.EnsureActivatedBoundary("hud_prefix");
                controller.VerifyPreXamlBoundary();
            }
        }

        private static void HudMainConstructorPostfix(object __instance)
        {
            RosterRuntimeController controller = _current;
            if (controller != null)
            {
                controller.QueueHudBoundary(__instance);
            }
        }

        private static void HudMainLoadedPostfix(object __instance, object __0)
        {
            RosterRuntimeController controller = _current;
            if (controller != null)
            {
                controller.NotifyHudLoaded(__instance, __0);
            }
        }

        private void VerifyPreXamlBoundary()
        {
            if (!_active || _failed)
            {
                return;
            }
            try
            {
                RequireMainThread();
                VerifyEffectiveXamlAssets();
                VerifyCoreOwnershipBoundary();
            }
            catch (Exception exception)
            {
                FailClosed("monitor_failed", exception.ToString(), true);
            }
        }

        private bool VerifyCoreOwnershipBoundary()
        {
            if (!string.Equals(FatControler.locale, _activeLocale, StringComparison.Ordinal))
            {
                FailClosed(
                    "locale_changed",
                    "FatControler.locale changed from " + _activeLocale
                    + " to " + Convert.ToString(FatControler.locale),
                    true);
                return false;
            }
            if (!ReferenceEquals(Translate.Instance.GameTexts, _gameTexts))
            {
                FailClosed(
                    "dictionary_changed",
                    "Translate.Instance.GameTexts identity changed",
                    true);
                return false;
            }
            if (!TranslationDictionaryIdentitiesMatch())
            {
                FailClosed(
                    "extender_dictionary_changed",
                    "A SHCDE-SE translation dictionary identity changed",
                    true);
                return false;
            }
            string conflict;
            if (RosterConflictDetector.TryFindConflict(
                _manifest.Entries,
                _translationDictionaries,
                _localizedDictionary,
                out conflict))
            {
                FailClosed(
                    "translation_conflict",
                    "A SHCDE-SE override appeared after activation: " + conflict,
                    true);
                return false;
            }
            string ownershipReason;
            if (!_mutation.VerifyOwnership(out ownershipReason))
            {
                FailClosed("ownership_lost", ownershipReason, true);
                return false;
            }
            return true;
        }

        private void EnsureActivatedBoundary(string boundary)
        {
            if (_active || _failed)
            {
                return;
            }
            try
            {
                EnsureActivatedOrThrow(boundary);
            }
            catch (Exception exception)
            {
                FailClosed("activation_failed", exception.ToString(), false);
            }
        }

        private void EnsureActivatedOrThrow(string boundary)
        {
            RequireMainThread();
            if (!_prepared && boundary != "startup")
            {
                throw new InvalidOperationException(
                    "Roster activation occurred before preparation");
            }
            if (_active)
            {
                return;
            }
            string locale = FatControler.locale;
            if (string.IsNullOrEmpty(locale)
                || !string.Equals(locale, locale.Trim(), StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "FatControler.locale is unavailable/noncanonical at " + boundary);
            }
            if (!RuntimeDecision.SupportsPinnedRosterLocale(locale))
            {
                throw new InvalidOperationException(
                    "Roster runtime target/original fingerprints support only dede; actual="
                    + locale);
            }
            FieldInfo hudMainField = typeof(MainViewModel).GetField(
                "HUDmain",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (hudMainField == null
                || !string.Equals(
                    hudMainField.FieldType.FullName,
                    "CrusaderDE.HUD_Main",
                    StringComparison.Ordinal))
            {
                throw new MissingFieldException(
                    "Exact MainViewModel.HUDmain field was not found");
            }
            FieldInfo mainViewModelInstanceField = typeof(MainViewModel).GetField(
                "instance",
                BindingFlags.NonPublic
                | BindingFlags.Static
                | BindingFlags.DeclaredOnly);
            if (mainViewModelInstanceField == null
                || mainViewModelInstanceField.FieldType != typeof(MainViewModel))
            {
                throw new MissingFieldException(
                    "Exact MainViewModel.instance field was not found");
            }
            FieldInfo mainUiLoadedField = typeof(MainViewModel).GetField(
                "MainUILoaded",
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (mainUiLoadedField == null
                || mainUiLoadedField.FieldType != typeof(bool))
            {
                throw new MissingFieldException(
                    "Exact MainViewModel.MainUILoaded field was not found");
            }
            _hudMainField = hudMainField;
            _mainViewModelInstanceField = mainViewModelInstanceField;
            _mainUiLoadedField = mainUiLoadedField;
            object mainViewModel = mainViewModelInstanceField.GetValue(null);
            if (mainViewModel != null
                && mainViewModel.GetType() != typeof(MainViewModel))
            {
                throw new InvalidOperationException(
                    "MainViewModel.instance type is not exact");
            }
            if (mainViewModel != null
                && hudMainField.GetValue(mainViewModel) != null)
            {
                throw new InvalidOperationException(
                    "Roster runtime loaded after HUD_Main construction; restart required");
            }
            VerifyEffectiveXamlAssets();

            Translate translate = Translate.Instance;
            if (translate == null || translate.GetType() != typeof(Translate))
            {
                throw new InvalidOperationException(
                    "Translate.Instance type is not exact");
            }
            Dictionary<string, string> gameTexts = translate.GameTexts;
            if (gameTexts == null || gameTexts.Count == 0)
            {
                throw new InvalidDataException(
                    "Translate.Instance.GameTexts is unavailable/empty");
            }

            CaptureTranslationDictionaries();
            string conflict;
            if (RosterConflictDetector.TryFindConflict(
                _manifest.Entries,
                _translationDictionaries,
                _localizedDictionary,
                out conflict))
            {
                throw new InvalidOperationException(
                    "SHCDE-SE translation route is already owned: " + conflict);
            }

            string originalsDigest = RosterMutationState.ComputeOriginalsDigest(
                gameTexts,
                _manifest.Entries);
            if (!string.Equals(
                originalsDigest,
                _manifest.TargetOriginalsSha256,
                StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster original text digest mismatch: expected="
                    + _manifest.TargetOriginalsSha256
                    + " actual=" + originalsDigest);
            }

            const bool german = true;
            RosterMutationState mutation = null;
            try
            {
                mutation = RosterMutationState.Apply(
                    gameTexts,
                    _manifest.Entries,
                    german);
                if (RosterConflictDetector.TryFindConflict(
                    _manifest.Entries,
                    _translationDictionaries,
                    _localizedDictionary,
                    out conflict))
                {
                    throw new InvalidOperationException(
                        "SHCDE-SE translation route changed during activation: "
                        + conflict);
                }
                string ownershipReason;
                if (!mutation.VerifyOwnership(out ownershipReason))
                {
                    throw new InvalidOperationException(
                        "Roster activation ownership verification failed: "
                        + ownershipReason);
                }
            }
            catch
            {
                if (mutation != null)
                {
                    mutation.RollbackOwned();
                }
                throw;
            }

            _mutation = mutation;
            _gameTexts = gameTexts;
            _activeLocale = locale;
            _active = true;
            _logInfo(RuntimeLogContract.RosterActive(
                "de-DE",
                _manifest.EntriesSha256));
        }

        private void CaptureTranslationDictionaries()
        {
            _translateApi = GameTranslateAPI.Instance;
            if (_translateApi == null
                || _translateApi.GetType() != typeof(GameTranslateAPI))
            {
                throw new InvalidOperationException(
                    "GameTranslateAPI.Instance type is not exact");
            }
            Type apiType = _translateApi.GetType();
            _translationFields = new FieldInfo[TranslationFieldNames.Length];
            _translationDictionaries = new IDictionary[TranslationFieldNames.Length];
            for (int index = 0; index < TranslationFieldNames.Length; index++)
            {
                FieldInfo field = apiType.GetField(
                    TranslationFieldNames[index],
                    BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly);
                if (field == null
                    || field.FieldType != typeof(Dictionary<string, string>))
                {
                    throw new MissingFieldException(
                        "Exact SHCDE-SE translation field was not found: "
                        + TranslationFieldNames[index]);
                }
                IDictionary dictionary = field.GetValue(_translateApi) as IDictionary;
                if (dictionary == null)
                {
                    throw new InvalidDataException(
                        "SHCDE-SE translation field is null: "
                        + TranslationFieldNames[index]);
                }
                _translationFields[index] = field;
                _translationDictionaries[index] = dictionary;
            }
            _localizedField = apiType.GetField(
                "_localizedTexts",
                BindingFlags.NonPublic
                | BindingFlags.Instance
                | BindingFlags.DeclaredOnly);
            if (_localizedField == null
                || _localizedField.FieldType
                    != typeof(Dictionary<string, Dictionary<string, string>>))
            {
                throw new MissingFieldException(
                    "Exact SHCDE-SE localized translation field was not found");
            }
            _localizedDictionary = _localizedField.GetValue(_translateApi) as IDictionary;
            if (_localizedDictionary == null)
            {
                throw new InvalidDataException(
                    "SHCDE-SE localized translation dictionary is null");
            }
        }

        private bool TranslationDictionaryIdentitiesMatch()
        {
            if (_translateApi == null
                || !ReferenceEquals(GameTranslateAPI.Instance, _translateApi)
                || _translationFields == null
                || _translationDictionaries == null
                || _localizedField == null
                || !ReferenceEquals(
                    _localizedField.GetValue(_translateApi),
                    _localizedDictionary))
            {
                return false;
            }
            for (int index = 0; index < _translationFields.Length; index++)
            {
                if (!ReferenceEquals(
                    _translationFields[index].GetValue(_translateApi),
                    _translationDictionaries[index]))
                {
                    return false;
                }
            }
            return true;
        }

        private void QueueHudBoundary(object instance)
        {
            if (!_active || _failed)
            {
                return;
            }
            try
            {
                RequireMainThread();
                VerifyEffectiveXamlAssets();
                if (instance == null || instance.GetType() != typeof(HUD_Main))
                {
                    throw new InvalidOperationException(
                        "HUD_Main constructor instance type is not exact");
                }
                RequireCurrentHudInstance(instance);
                object prior = PendingHudInstance();
                if (prior != null && !ReferenceEquals(prior, instance))
                {
                    throw new InvalidOperationException(
                        "A second HUD_Main generation was constructed before the first "
                        + "generation's bindings resolved");
                }
                _pendingHudInstance = new WeakReference(instance);
                _pendingHudLoaded = false;
            }
            catch (Exception exception)
            {
                FailClosed("hud_verification_failed", exception.ToString(), true);
            }
        }

        private void NotifyHudLoaded(object instance, object sender)
        {
            if (!_active || _failed)
            {
                return;
            }
            object pending = PendingHudInstance();
            if (_pendingHudInstance == null || !ReferenceEquals(pending, instance))
            {
                // A late Loaded callback from a superseded/verified generation
                // must never release the currently pending generation.
                return;
            }
            try
            {
                RequireMainThread();
                object mainViewModel = RequireCurrentHudInstance(instance);
                if (!ReadMainUiLoaded(mainViewModel))
                {
                    throw new InvalidOperationException(
                        "HUD_Main Loaded postfix observed MainUILoaded=false");
                }
                RequireLoadedGuideRect(instance, sender);
                _pendingHudLoaded = true;
            }
            catch (Exception exception)
            {
                FailClosed("hud_verification_failed", exception.ToString(), true);
            }
        }

        private bool ProcessPendingHudBoundary()
        {
            object instance = PendingHudInstance();
            if (_pendingHudInstance == null)
            {
                return true;
            }
            if (instance == null)
            {
                ClearPendingHudBoundary();
                FailClosed(
                    "hud_verification_failed",
                    "Pending HUD_Main generation was disposed before binding verification",
                    true);
                return false;
            }
            try
            {
                RequireMainThread();
                object mainViewModel = RequireCurrentHudInstance(instance);
                if (!_pendingHudLoaded)
                {
                    if (ReadMainUiLoaded(mainViewModel))
                    {
                        throw new InvalidOperationException(
                            "HUD_Main lifecycle desynchronized: MainUILoaded=true "
                            + "without the matching Loaded callback");
                    }
                    return false;
                }
                if (!ReadMainUiLoaded(mainViewModel))
                {
                    throw new InvalidOperationException(
                        "HUD_Main unloaded before binding verification");
                }
                VerifyEffectiveXamlAssets();
                RequireLoadedGuideRect(instance, null);
                MethodInfo findName = RequireFindNameMethod(instance);
                Dictionary<string, RosterTextEntry> byKey =
                    new Dictionary<string, RosterTextEntry>(StringComparer.Ordinal);
                foreach (RosterTextEntry entry in _manifest.Entries)
                {
                    byKey.Add(entry.InternalKey, entry);
                }
                bool german = string.Equals(_activeLocale, "dede", StringComparison.Ordinal);
                List<RosterOwnedStringSlot> generation =
                    new List<RosterOwnedStringSlot>();
                foreach (RosterHudBinding binding in _manifest.HudBindings)
                {
                    object control = findName.Invoke(instance, new object[] { binding.Control });
                    if (control == null)
                    {
                        throw new InvalidDataException(
                            "Roster HUD control is missing: " + binding.Control);
                    }
                    PropertyInfo tagProperty = control.GetType().GetProperty(
                        "Tag",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (tagProperty == null
                        || !tagProperty.CanRead
                        || !tagProperty.CanWrite)
                    {
                        throw new MissingMemberException(
                            "Roster HUD control Tag property is unavailable: "
                            + binding.Control);
                    }
                    PropertyInfo tagDependencyProperty = control.GetType().GetProperty(
                        "TagProperty",
                        BindingFlags.Public
                        | BindingFlags.Static
                        | BindingFlags.FlattenHierarchy);
                    if (tagDependencyProperty == null
                        || !tagDependencyProperty.CanRead
                        || tagDependencyProperty.GetIndexParameters().Length != 0
                        || !string.Equals(
                            tagDependencyProperty.PropertyType.FullName,
                            "Noesis.DependencyProperty",
                            StringComparison.Ordinal))
                    {
                        throw new MissingMemberException(
                            "Roster HUD control TagProperty is unavailable/nonexact: "
                            + binding.Control);
                    }
                    object dependencyProperty = tagDependencyProperty.GetValue(null, null);
                    if (dependencyProperty == null
                        || dependencyProperty.GetType() != tagDependencyProperty.PropertyType)
                    {
                        throw new InvalidOperationException(
                            "Roster HUD control TagProperty value is unavailable/nonexact: "
                            + binding.Control);
                    }
                    MethodInfo getBindingExpression = control.GetType().GetMethod(
                        "GetBindingExpression",
                        BindingFlags.Public | BindingFlags.Instance,
                        null,
                        new[] { tagDependencyProperty.PropertyType },
                        null);
                    if (getBindingExpression == null
                        || !string.Equals(
                            getBindingExpression.ReturnType.FullName,
                            "Noesis.BindingExpression",
                            StringComparison.Ordinal))
                    {
                        throw new MissingMethodException(
                            "Roster HUD control GetBindingExpression is unavailable/nonexact: "
                            + binding.Control);
                    }
                    object bindingExpression = getBindingExpression.Invoke(
                        control,
                        new[] { dependencyProperty });
                    if (bindingExpression == null
                        || !string.Equals(
                            bindingExpression.GetType().FullName,
                            "Noesis.BindingExpression",
                            StringComparison.Ordinal))
                    {
                        throw new InvalidDataException(
                            "Roster HUD control TagProperty is not bound: "
                            + binding.Control);
                    }
                    MethodInfo updateTarget = bindingExpression.GetType().GetMethod(
                        "UpdateTarget",
                        BindingFlags.Public | BindingFlags.Instance,
                        null,
                        Type.EmptyTypes,
                        null);
                    if (updateTarget == null || updateTarget.ReturnType != typeof(void))
                    {
                        throw new MissingMethodException(
                            "Roster HUD binding UpdateTarget() is unavailable/nonexact: "
                            + binding.Control);
                    }
                    updateTarget.Invoke(bindingExpression, null);
                    RosterTextEntry entry;
                    if (!byKey.TryGetValue(binding.InternalKey, out entry))
                    {
                        throw new InvalidDataException(
                            "Roster HUD binding key is absent: "
                            + binding.InternalKey);
                    }
                    string owned = entry.OwnedValue(german);
                    object actual = tagProperty.GetValue(control, null);
                    if (!string.Equals(actual as string, owned, StringComparison.Ordinal))
                    {
                        string dictionaryValue;
                        _gameTexts.TryGetValue(binding.InternalKey, out dictionaryValue);
                        throw new InvalidDataException(
                            "Roster HUD Tag did not bind the owned value: "
                            + binding.Control
                            + " actual=" + DescribeTextValue(actual)
                            + " dictionary=" + DescribeTextValue(dictionaryValue)
                            + " expected=" + DescribeTextValue(owned));
                    }
                    object localControl = control;
                    PropertyInfo localTagProperty = tagProperty;
                    generation.Add(new RosterOwnedStringSlot(
                        () => localTagProperty.GetValue(localControl, null) as string,
                        value => localTagProperty.SetValue(localControl, value, null),
                        _mutation.Originals[binding.InternalKey],
                        owned));
                }
                if (generation.Count != _manifest.HudBindings.Length
                    || generation.Count != 17)
                {
                    throw new InvalidDataException(
                        "Roster HUD binding generation is incomplete: "
                        + generation.Count);
                }
                int supersededRestored = _hudOwnership.Replace(generation);
                if (supersededRestored != 0)
                {
                    _logInfo(
                        "Superseded roster HUD generation conditionally restored controls="
                        + supersededRestored);
                }
                ClearPendingHudBoundary();
                _hudGeneration++;
                _logInfo(RuntimeLogContract.RosterHudVerified(_hudGeneration));
                // Ownership and the one-shot healthy terminal are checked on
                // the following persistent host tick, never in this signal tick.
                return false;
            }
            catch (Exception exception)
            {
                int restoredUnregistered = RestoreUnregisteredHudTags(instance);
                ClearPendingHudBoundary();
                if (restoredUnregistered != 0)
                {
                    _logWarning(
                        "Failed HUD generation conditionally restored controls="
                        + restoredUnregistered);
                }
                FailClosed("hud_verification_failed", exception.ToString(), true);
                return false;
            }
        }

        private object PendingHudInstance()
        {
            return _pendingHudInstance == null
                ? null
                : _pendingHudInstance.Target;
        }

        private void ClearPendingHudBoundary()
        {
            _pendingHudInstance = null;
            _pendingHudLoaded = false;
        }

        private object RequireCurrentHudInstance(object instance)
        {
            if (_mainViewModelInstanceField == null
                || _hudMainField == null
                || _mainUiLoadedField == null)
            {
                throw new InvalidOperationException(
                    "MainViewModel roster lifecycle fields were not captured");
            }
            object mainViewModel = _mainViewModelInstanceField.GetValue(null);
            if (mainViewModel == null || mainViewModel.GetType() != typeof(MainViewModel))
            {
                throw new InvalidOperationException(
                    "MainViewModel.instance is unavailable/nonexact at the HUD boundary");
            }
            if (!ReferenceEquals(_hudMainField.GetValue(mainViewModel), instance))
            {
                throw new InvalidOperationException(
                    "MainViewModel.HUDmain does not own the pending HUD_Main instance");
            }
            return mainViewModel;
        }

        private bool ReadMainUiLoaded(object mainViewModel)
        {
            object value = _mainUiLoadedField.GetValue(mainViewModel);
            if (!(value is bool))
            {
                throw new InvalidOperationException(
                    "MainViewModel.MainUILoaded value is nonexact");
            }
            return (bool)value;
        }

        private static MethodInfo RequireFindNameMethod(object instance)
        {
            MethodInfo findName = instance.GetType().GetMethod(
                "FindName",
                BindingFlags.Public | BindingFlags.Instance,
                null,
                new[] { typeof(string) },
                null);
            if (findName == null)
            {
                throw new MissingMethodException(
                    "HUD_Main.FindName(string) is unavailable");
            }
            return findName;
        }

        private static object RequireLoadedGuideRect(object instance, object expectedSender)
        {
            MethodInfo findName = RequireFindNameMethod(instance);
            object guideRect = findName.Invoke(instance, new object[] { "GuideRect" });
            if (guideRect == null
                || !string.Equals(
                    guideRect.GetType().FullName,
                    "Noesis.Rectangle",
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "HUD_Main.GuideRect is unavailable/nonexact");
            }
            if (expectedSender != null && !ReferenceEquals(guideRect, expectedSender))
            {
                throw new InvalidOperationException(
                    "HUD_Main Loaded sender is not the exact GuideRect instance");
            }
            PropertyInfo isLoaded = guideRect.GetType().GetProperty(
                "IsLoaded",
                BindingFlags.Public | BindingFlags.Instance);
            if (isLoaded == null
                || !isLoaded.CanRead
                || isLoaded.PropertyType != typeof(bool)
                || isLoaded.GetIndexParameters().Length != 0
                || !((bool)isLoaded.GetValue(guideRect, null)))
            {
                throw new InvalidOperationException(
                    "HUD_Main.GuideRect is not loaded at the exact lifecycle boundary");
            }
            return guideRect;
        }

        private int RestoreUnregisteredHudTags(object instance)
        {
            if (instance == null || _manifest == null || _mutation == null)
            {
                return 0;
            }
            int restored = 0;
            try
            {
                MethodInfo findName = instance.GetType().GetMethod(
                    "FindName",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(string) },
                    null);
                if (findName == null)
                {
                    return 0;
                }
                Dictionary<string, RosterTextEntry> byKey =
                    new Dictionary<string, RosterTextEntry>(StringComparer.Ordinal);
                foreach (RosterTextEntry entry in _manifest.Entries)
                {
                    byKey[entry.InternalKey] = entry;
                }
                foreach (RosterHudBinding binding in _manifest.HudBindings)
                {
                    try
                    {
                        object control = findName.Invoke(
                            instance,
                            new object[] { binding.Control });
                        if (control == null)
                        {
                            continue;
                        }
                        PropertyInfo tagProperty = control.GetType().GetProperty(
                            "Tag",
                            BindingFlags.Public | BindingFlags.Instance);
                        RosterTextEntry entry;
                        if (tagProperty == null
                            || !tagProperty.CanRead
                            || !tagProperty.CanWrite
                            || !byKey.TryGetValue(binding.InternalKey, out entry))
                        {
                            continue;
                        }
                        string owned = entry.OwnedValue(true);
                        if (string.Equals(
                            tagProperty.GetValue(control, null) as string,
                            owned,
                            StringComparison.Ordinal))
                        {
                            string original = _mutation.Originals[binding.InternalKey];
                            tagProperty.SetValue(
                                control,
                                original,
                                null);
                            if (string.Equals(
                                tagProperty.GetValue(control, null) as string,
                                original,
                                StringComparison.Ordinal))
                            {
                                restored++;
                            }
                        }
                    }
                    catch
                    {
                        // This is a best-effort, value-owned cleanup of a HUD
                        // generation that already failed exact verification.
                    }
                }
            }
            catch
            {
                return restored;
            }
            return restored;
        }

        private bool VerifyHudOwnership(out string reason)
        {
            return _hudOwnership.VerifyOwnership(out reason);
        }

        private static string DescribeTextValue(object value)
        {
            if (value == null)
            {
                return "null";
            }
            string text = value as string;
            if (text == null)
            {
                return "type=" + value.GetType().FullName;
            }
            return "type=System.String,length=" + text.Length
                + ",sha256="
                + Hashing.Sha256(System.Text.Encoding.UTF8.GetBytes(text));
        }

        private void FailClosed(string reason, string detail, bool restartRequired)
        {
            if (_failed)
            {
                return;
            }
            _failed = true;
            _restartRequired = restartRequired;
            if (restartRequired)
            {
                _logError(RuntimeLogContract.RosterRestartRequired(reason));
            }
            else
            {
                _logError(RuntimeLogContract.RosterFailedClosed(reason));
            }
            _logError("Roster runtime detail: " + detail);
            RollbackOwned(false);
        }

        private void VerifyEffectiveXamlAssets()
        {
            VerifyPinnedInputHashes();
            VerifyEffectiveXamlAsset(
                "Assets/GUI/XAMLResources/HUD_Main.xaml",
                _manifest.HudXamlRelativePath,
                _hudXamlFullPath,
                "hud_xaml");
            VerifyEffectiveXamlAsset(
                "Assets/GUI/XAMLResources/HUD_Buildings.xaml",
                _manifest.HudBuildingsXamlRelativePath,
                _hudBuildingsXamlFullPath,
                "hud_buildings_xaml");
        }

        private void VerifyPinnedInputHashes()
        {
            VerifyPinnedFullPath(
                _targetTextFullPath,
                _manifest.TargetTextSize,
                _manifest.TargetTextSha256,
                "target_text");
            VerifyPinnedFullPath(
                _hudXamlFullPath,
                _manifest.HudXamlSize,
                _manifest.HudXamlSha256,
                "hud_xaml");
            VerifyPinnedFullPath(
                _hudBuildingsXamlFullPath,
                _manifest.HudBuildingsXamlSize,
                _manifest.HudBuildingsXamlSha256,
                "hud_buildings_xaml");
        }

        private void VerifyEffectiveXamlAsset(
            string logicalPath,
            string pinnedRelativePath,
            string expectedFullPath,
            string label)
        {
            const string overrideSegment = "/Override/";
            string normalizedPinned = pinnedRelativePath.Replace('\\', '/');
            int overrideIndex = normalizedPinned.IndexOf(
                overrideSegment,
                StringComparison.Ordinal);
            if (overrideIndex < 0
                || !string.Equals(
                    normalizedPinned.Substring(
                        overrideIndex + overrideSegment.Length),
                    logicalPath,
                    StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster pinned XAML path has an unexpected logical key: "
                    + label);
            }

            GameAssetManagerAPI assetManager = GameAssetManagerAPI.Instance;
            if (assetManager == null
                || assetManager.GetType() != typeof(GameAssetManagerAPI))
            {
                throw new InvalidOperationException(
                    "GameAssetManagerAPI.Instance type is not exact");
            }
            string resolvedPath;
            if (!assetManager.GetModifiedFilePath(logicalPath, out resolvedPath)
                || string.IsNullOrEmpty(resolvedPath))
            {
                throw new FileNotFoundException(
                    "Pinned XAML is not the effective SHCDE-SE asset: " + label);
            }
            string resolvedFullPath = Path.GetFullPath(resolvedPath);
            if (!string.Equals(
                resolvedFullPath,
                expectedFullPath,
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "A foreign provider owns the effective XAML asset: " + label);
            }

            bool allowOwnedFortificationPatch =
                GeneratedFortificationContract.Enabled
                && string.Equals(
                    logicalPath,
                    GeneratedFortificationContract.HudLogicalPath,
                    StringComparison.Ordinal);
            PinnedXamlOwnershipGuard.VerifyRegisteredPatches(
                logicalPath,
                _pluginDirectory,
                GeneratedFortificationContract.HudPatchRelativePath,
                GeneratedFortificationContract.HudPatchSize,
                GeneratedFortificationContract.HudPatchSha256,
                allowOwnedFortificationPatch);
        }

        private static string VerifyPinnedGameFile(
            string relativePath,
            long expectedSize,
            string expectedSha256,
            string label)
        {
            string root = Path.GetFullPath(Paths.GameRootPath)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string prefix = root + Path.DirectorySeparatorChar;
            string fullPath = Path.GetFullPath(Path.Combine(
                root,
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            if (!fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "Roster pinned path escapes the game root: " + label);
            }
            string actual = Hashing.Sha256FileStable(fullPath, expectedSize);
            if (!string.Equals(actual, expectedSha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster pinned file SHA-256 mismatch: " + label);
            }
            return fullPath;
        }

        private static void VerifyPinnedFullPath(
            string fullPath,
            long expectedSize,
            string expectedSha256,
            string label)
        {
            if (string.IsNullOrEmpty(fullPath))
            {
                throw new InvalidDataException(
                    "Roster pinned full path is unavailable: " + label);
            }
            string actual = Hashing.Sha256FileStable(fullPath, expectedSize);
            if (!string.Equals(actual, expectedSha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    "Roster pinned file changed before use: " + label);
            }
        }

        private void RequireMainThread()
        {
            if (Thread.CurrentThread.ManagedThreadId != _mainThreadId)
            {
                throw new InvalidOperationException(
                    "Roster runtime mutation must remain on its Unity main thread");
            }
        }
    }
}
