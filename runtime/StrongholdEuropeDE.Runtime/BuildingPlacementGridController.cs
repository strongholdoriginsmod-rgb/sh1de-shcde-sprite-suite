using System;
using System.Reflection;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Binds the one Script-Extender entry point used by the placement grid.
    /// Every part of the reflected surface is pinned so an extender update
    /// cannot silently redirect the feature to a similarly named method.
    /// </summary>
    internal static class BuildingPlacementGridReflection
    {
        internal const string ExpectedApiTypeName =
            "SHCDESE.API.GameTileManagerAPI";

        internal static Action<int, bool> Bind(Type apiType)
        {
            return BindExact(apiType, ExpectedApiTypeName);
        }

        internal static Action<int, bool> BindExact(
            Type apiType,
            string expectedTypeName)
        {
            if (apiType == null)
            {
                throw new ArgumentNullException("apiType");
            }
            if (string.IsNullOrEmpty(expectedTypeName)
                || !string.Equals(
                    apiType.FullName,
                    expectedTypeName,
                    StringComparison.Ordinal)
                || !apiType.IsSealed)
            {
                throw new MissingMemberException(
                    "Exact sealed GameTileManagerAPI type was not found");
            }

            PropertyInfo instanceProperty = apiType.GetProperty(
                "Instance",
                BindingFlags.Public
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly);
            MethodInfo getter = instanceProperty == null
                ? null
                : instanceProperty.GetGetMethod(false);
            if (instanceProperty == null
                || instanceProperty.PropertyType != apiType
                || instanceProperty.GetIndexParameters().Length != 0
                || getter == null
                || !getter.IsPublic
                || !getter.IsStatic
                || getter.GetParameters().Length != 0
                || instanceProperty.GetSetMethod(true) != null)
            {
                throw new MissingMemberException(
                    "Exact public static GameTileManagerAPI.Instance getter was not found");
            }

            MethodInfo setter = null;
            int namedMethods = 0;
            MethodInfo[] methods = apiType.GetMethods(
                BindingFlags.Public
                    | BindingFlags.NonPublic
                    | BindingFlags.Instance
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly);
            for (int index = 0; index < methods.Length; index++)
            {
                if (!string.Equals(
                    methods[index].Name,
                    "SetDebugRendering",
                    StringComparison.Ordinal))
                {
                    continue;
                }
                namedMethods++;
                setter = methods[index];
            }
            if (namedMethods != 1 || setter == null)
            {
                throw new MissingMethodException(
                    "GameTileManagerAPI must declare exactly one SetDebugRendering method");
            }

            ParameterInfo[] parameters = setter.GetParameters();
            object forceDefault = parameters.Length == 2
                ? parameters[1].DefaultValue
                : null;
            if (!setter.IsAssembly
                || setter.IsPublic
                || setter.IsStatic
                || setter.ReturnType != typeof(void)
                || setter.ContainsGenericParameters
                || parameters.Length != 2
                || parameters[0].ParameterType != typeof(int)
                || parameters[0].IsOptional
                || !string.Equals(
                    parameters[0].Name,
                    "mode",
                    StringComparison.Ordinal)
                || parameters[1].ParameterType != typeof(bool)
                || !parameters[1].IsOptional
                || !parameters[1].HasDefaultValue
                || !(forceDefault is bool)
                || (bool)forceDefault
                || !string.Equals(
                    parameters[1].Name,
                    "force",
                    StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "Exact internal void SetDebugRendering(int mode, bool force=false) method was not found");
            }

            object instance = instanceProperty.GetValue(null, null);
            if (instance == null || instance.GetType() != apiType)
            {
                throw new InvalidOperationException(
                    "GameTileManagerAPI.Instance returned no exact singleton instance");
            }

            return delegate(int mode, bool force)
            {
                setter.Invoke(instance, new object[] { mode, force });
            };
        }
    }

    internal readonly struct BuildingPlacementGridInputState
    {
        internal BuildingPlacementGridInputState(
            bool controlHeld,
            bool altHeld,
            bool gPressedThisFrame)
        {
            ControlHeld = controlHeld;
            AltHeld = altHeld;
            GPressedThisFrame = gPressedThisFrame;
        }

        internal bool ControlHeld { get; }

        internal bool AltHeld { get; }

        internal bool GPressedThisFrame { get; }
    }

    /// <summary>
    /// Resolves legacy Unity input without adding InputLegacyModule to the
    /// runtime project's compile-time references. The two Unity assembly and
    /// type identities plus both method signatures remain fail-closed.
    /// </summary>
    internal static class BuildingPlacementGridInputReflection
    {
        private const string InputTypeName = "UnityEngine.Input";
        private const string InputAssemblyName = "UnityEngine.InputLegacyModule";
        private const string KeyCodeTypeName = "UnityEngine.KeyCode";
        private const string KeyCodeAssemblyName = "UnityEngine.CoreModule";

        internal static Func<BuildingPlacementGridInputState> Bind()
        {
            Type inputType = Type.GetType(
                InputTypeName + ", " + InputAssemblyName,
                false);
            Type keyCodeType = Type.GetType(
                KeyCodeTypeName + ", " + KeyCodeAssemblyName,
                false);
            if (inputType == null || keyCodeType == null)
            {
                throw new MissingMemberException(
                    "Exact Unity legacy input types were not found");
            }
            if (!string.Equals(
                    inputType.Assembly.GetName().Name,
                    InputAssemblyName,
                    StringComparison.Ordinal)
                || !string.Equals(
                    keyCodeType.Assembly.GetName().Name,
                    KeyCodeAssemblyName,
                    StringComparison.Ordinal))
            {
                throw new MissingMemberException(
                    "Unity legacy input assembly identities changed");
            }
            return BindExact(inputType, keyCodeType);
        }

        internal static Func<BuildingPlacementGridInputState> BindExact(
            Type inputType,
            Type keyCodeType)
        {
            if (inputType == null)
            {
                throw new ArgumentNullException("inputType");
            }
            if (keyCodeType == null)
            {
                throw new ArgumentNullException("keyCodeType");
            }
            if (!string.Equals(
                inputType.FullName,
                    InputTypeName,
                    StringComparison.Ordinal)
                || inputType.IsAbstract
                || inputType.IsSealed
                || inputType.BaseType != typeof(object)
                || !string.Equals(
                    keyCodeType.FullName,
                    KeyCodeTypeName,
                    StringComparison.Ordinal)
                || !keyCodeType.IsEnum
                || Enum.GetUnderlyingType(keyCodeType) != typeof(int))
            {
                throw new MissingMemberException(
                    "Exact Unity Input/KeyCode surface was not found");
            }

            MethodInfo getKey = RequireInputMethod(
                inputType,
                "GetKey",
                keyCodeType);
            MethodInfo getKeyDown = RequireInputMethod(
                inputType,
                "GetKeyDown",
                keyCodeType);
            object leftControl = RequireKeyCode(keyCodeType, "LeftControl");
            object rightControl = RequireKeyCode(keyCodeType, "RightControl");
            object leftAlt = RequireKeyCode(keyCodeType, "LeftAlt");
            object rightAlt = RequireKeyCode(keyCodeType, "RightAlt");
            object g = RequireKeyCode(keyCodeType, "G");

            return delegate
            {
                object[] argument = new object[1];
                argument[0] = leftControl;
                bool controlHeld = (bool)getKey.Invoke(null, argument);
                if (!controlHeld)
                {
                    argument[0] = rightControl;
                    controlHeld = (bool)getKey.Invoke(null, argument);
                }
                argument[0] = leftAlt;
                bool altHeld = (bool)getKey.Invoke(null, argument);
                if (!altHeld)
                {
                    argument[0] = rightAlt;
                    altHeld = (bool)getKey.Invoke(null, argument);
                }
                argument[0] = g;
                bool gPressedThisFrame = (bool)getKeyDown.Invoke(null, argument);
                return new BuildingPlacementGridInputState(
                    controlHeld,
                    altHeld,
                    gPressedThisFrame);
            };
        }

        private static MethodInfo RequireInputMethod(
            Type inputType,
            string name,
            Type keyCodeType)
        {
            MethodInfo method = inputType.GetMethod(
                name,
                BindingFlags.Public
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly,
                null,
                new[] { keyCodeType },
                null);
            if (method == null
                || method.ReturnType != typeof(bool)
                || method.ContainsGenericParameters
                || method.GetParameters().Length != 1)
            {
                throw new MissingMethodException(
                    "Exact UnityEngine.Input." + name
                    + "(KeyCode) method was not found");
            }
            return method;
        }

        private static object RequireKeyCode(Type keyCodeType, string name)
        {
            if (!Enum.IsDefined(keyCodeType, name))
            {
                throw new MissingFieldException(
                    "UnityEngine.KeyCode." + name + " was not found");
            }
            return Enum.Parse(keyCodeType, name, false);
        }
    }

    /// <summary>
    /// Reads back the mode field which the game itself accepted. The
    /// extender's SetDebugRendering method does not propagate execution
    /// failures, so a returned reflection invocation is not an acknowledgement.
    /// On the pinned main-thread topology its dispatcher executes immediately;
    /// an unchanged activation readback is therefore unsupported and fenced by
    /// a compensating FIFO restore. Even a matching field does not prove that
    /// GameMap's later tile clear/render work completed.
    /// </summary>
    internal static class BuildingPlacementGridReadbackReflection
    {
        internal const string ExpectedGameMapTypeName = "GameMap";
        internal const string ExpectedAssemblyName = "Assembly-CSharp";

        internal static Func<int?> Bind(Type gameMapType)
        {
            return BindExact(
                gameMapType,
                ExpectedGameMapTypeName,
                ExpectedAssemblyName);
        }

        internal static Func<int?> BindExact(
            Type gameMapType,
            string expectedTypeName,
            string expectedAssemblyName)
        {
            if (gameMapType == null)
            {
                throw new ArgumentNullException("gameMapType");
            }
            if (string.IsNullOrEmpty(expectedTypeName)
                || string.IsNullOrEmpty(expectedAssemblyName)
                || !string.Equals(
                    gameMapType.FullName,
                    expectedTypeName,
                    StringComparison.Ordinal)
                || !string.Equals(
                    gameMapType.Assembly.GetName().Name,
                    expectedAssemblyName,
                    StringComparison.Ordinal)
                || !gameMapType.IsClass
                || !gameMapType.IsPublic
                || gameMapType.IsAbstract
                || gameMapType.IsSealed
                || gameMapType.BaseType == null
                || !string.Equals(
                    gameMapType.BaseType.FullName,
                    "UnityEngine.MonoBehaviour",
                    StringComparison.Ordinal))
            {
                throw new MissingMemberException(
                    "Exact Assembly-CSharp GameMap type was not found");
            }

            FieldInfo instanceField = gameMapType.GetField(
                "instance",
                BindingFlags.Public
                    | BindingFlags.Static
                    | BindingFlags.DeclaredOnly);
            if (instanceField == null
                || instanceField.FieldType != gameMapType
                || instanceField.IsInitOnly
                || instanceField.IsLiteral)
            {
                throw new MissingFieldException(
                    "Exact public static mutable GameMap.instance field was not found");
            }

            PropertyInfo modeProperty = gameMapType.GetProperty(
                "DebugLayerRendering",
                BindingFlags.Public
                    | BindingFlags.Instance
                    | BindingFlags.DeclaredOnly);
            MethodInfo getter = modeProperty == null
                ? null
                : modeProperty.GetGetMethod(false);
            if (modeProperty == null
                || modeProperty.PropertyType != typeof(int)
                || modeProperty.GetIndexParameters().Length != 0
                || modeProperty.GetSetMethod(true) != null
                || getter == null
                || !getter.IsPublic
                || getter.IsStatic
                || getter.IsVirtual
                || getter.GetParameters().Length != 0)
            {
                throw new MissingMemberException(
                    "Exact public read-only GameMap.DebugLayerRendering property was not found");
            }

            return delegate
            {
                object instance = instanceField.GetValue(null);
                if (instance == null)
                {
                    return null;
                }
                if (instance.GetType() != gameMapType)
                {
                    throw new InvalidOperationException(
                        "GameMap.instance does not contain the exact GameMap type");
                }
                object value = modeProperty.GetValue(instance, null);
                if (!(value is int))
                {
                    throw new InvalidOperationException(
                        "GameMap.DebugLayerRendering returned no integer mode");
                }
                return (int)value;
            };
        }
    }

    /// <summary>
    /// Dependency-free state machine for the Ctrl+Alt+G placement grid.
    /// The Unity input and SHCDE-SE lifecycle adapters live in the companion
    /// feature file; this core owns all fail-closed state transitions.
    /// </summary>
    internal sealed class BuildingPlacementGridController
    {
        internal const int StructureLayerMode = 1;
        internal const int ActivatorMode = 5;
        internal const int DisabledMode = -1;
        internal const int AcceptancePollLimit = 8;
        internal const bool EnabledByDefault = false;

        private enum PendingPurpose
        {
            None,
            SelectStructureLayer,
            ActivateStructureLayer,
            RestoreOwnedBaseline,
        }

        private readonly Action<int, bool> _setDebugRendering;
        private readonly Func<int?> _readDebugRendering;
        private readonly Action<string> _info;
        private readonly Action<string> _error;

        private bool _mapActive;
        private int? _observedMode;
        private bool _requestPending;
        private int _pendingMode;
        private int _pendingPreviousMode;
        private int _pendingPollsRemaining;
        private string _pendingTrigger;
        private bool _pendingEmergencyReset;
        private PendingPurpose _pendingPurpose;
        private bool _ownershipClaimed;
        private bool _activationSequenceObserved;
        private int _ownedBaselineMode = DisabledMode;
        private bool _fifoCompensationQueued;
        private int _fifoCompensationPrecursorMode = DisabledMode;
        private bool _fifoCompensationPrecursorObserved;
        private bool _fifoCompensationDeviationObserved;
        private bool _failed;
        private bool _rolledBack;
        private bool _rollbackInProgress;
        private string _failure;

        internal BuildingPlacementGridController(
            Action<int, bool> setDebugRendering,
            Func<int?> readDebugRendering,
            Action<string> info,
            Action<string> error)
        {
            if (setDebugRendering == null)
            {
                throw new ArgumentNullException("setDebugRendering");
            }
            if (readDebugRendering == null)
            {
                throw new ArgumentNullException("readDebugRendering");
            }
            if (info == null)
            {
                throw new ArgumentNullException("info");
            }
            if (error == null)
            {
                throw new ArgumentNullException("error");
            }
            _setDebugRendering = setDebugRendering;
            _readDebugRendering = readDebugRendering;
            _info = info;
            _error = error;
        }

        internal bool MapActive
        {
            get { return _mapActive; }
        }

        internal bool StructureGridModeObserved
        {
            // Mode 5 is only meaningful to this feature after its own
            // -1 -> 1 -> 5 sequence was observed. Even then this reports the
            // GameMap field transition, not completion of the 640k-tile render.
            get
            {
                return _ownershipClaimed
                    && _activationSequenceObserved
                    && _observedMode.HasValue
                    && _observedMode.Value == ActivatorMode;
            }
        }

        internal int? ObservedMode
        {
            get { return _observedMode; }
        }

        internal bool RequestPending
        {
            get { return _requestPending; }
        }

        internal int? PendingMode
        {
            get
            {
                return _requestPending
                    ? (int?)_pendingMode
                    : null;
            }
        }

        internal bool Failed
        {
            get { return _failed; }
        }

        internal bool RolledBack
        {
            get { return _rolledBack; }
        }

        internal string Failure
        {
            get { return _failure; }
        }

        internal bool OnMapStarted()
        {
            if (_failed || _rolledBack)
            {
                return false;
            }
            _mapActive = true;
            if (!_ownershipClaimed && !_requestPending)
            {
                _observedMode = null;
            }
            LogInfo(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=map_ready|write=none|ownership="
                + (_ownershipClaimed ? "retained" : "none"));
            return true;
        }

        internal bool PollPendingAcceptance()
        {
            if (!_requestPending)
            {
                return false;
            }
            return ObservePendingAcceptance();
        }

        internal bool Tick(
            bool controlHeld,
            bool altHeld,
            bool gPressedThisFrame)
        {
            if (_failed
                || _rolledBack
                || !_mapActive
                || _requestPending
                || !controlHeld
                || !altHeld
                || !gPressedThisFrame)
            {
                return false;
            }

            int? observed;
            try
            {
                observed = _readDebugRendering();
            }
            catch (Exception exception)
            {
                FailClosed("hotkey_readback", exception);
                return false;
            }
            if (!observed.HasValue)
            {
                FailClosed(
                    "hotkey_readback",
                    new InvalidOperationException(
                        "GameMap.instance exposes no current debug mode"));
                return false;
            }
            _observedMode = observed.Value;
            if (_ownershipClaimed)
            {
                if (!_activationSequenceObserved
                    || observed.Value != ActivatorMode)
                {
                    HandleOwnershipDeviation(
                        "ctrl_alt_g",
                        observed.Value,
                        _activationSequenceObserved
                            ? ActivatorMode
                            : StructureLayerMode);
                    return false;
                }
                return RestoreOwnedMode("ctrl_alt_g_restore", false);
            }

            // GameMap owns one process-global debug mode. Taking it over from
            // any non-vanilla value would destroy a map-editor or foreign-mod
            // layer whose hidden activator state cannot be reconstructed.
            if (observed.Value != DisabledMode)
            {
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=activation_blocked|reason=foreign_mode"
                    + "|observed=" + observed.Value.ToString()
                    + "|write=none");
                return false;
            }

            _ownershipClaimed = true;
            _activationSequenceObserved = false;
            _ownedBaselineMode = observed.Value;
            return RequestMode(
                StructureLayerMode,
                "ctrl_alt_g_structure_layer",
                PendingPurpose.SelectStructureLayer,
                false,
                observed.Value);
        }

        internal bool OnMapUnload()
        {
            if (_rolledBack)
            {
                return false;
            }
            _mapActive = false;
            RestoreOwnedMode("map_unload_restore", false);
            return DrainTerminalRestore("map_unload");
        }

        internal void FailClosed(string trigger, Exception exception)
        {
            if (_rolledBack)
            {
                return;
            }
            RecordFailure(trigger, exception);
            RestoreOwnedMode(trigger + "_emergency_restore", true);
        }

        internal bool Rollback()
        {
            if (_rolledBack || _rollbackInProgress)
            {
                return !_ownershipClaimed && !_requestPending;
            }
            _rollbackInProgress = true;
            try
            {
                _mapActive = false;
                RestoreOwnedMode("rollback_restore", false);
                return DrainTerminalRestore("rollback");
            }
            finally
            {
                // Rollback becomes terminal only after the bounded readback /
                // retry drain. No later Tick or subscription is required to
                // finish (or honestly reject) the owned restore.
                _rolledBack = true;
                _rollbackInProgress = false;
                _mapActive = false;
            }
        }

        private bool RequestMode(
            int mode,
            string trigger,
            PendingPurpose purpose,
            bool emergencyReset,
            int previousMode)
        {
            if (previousMode == mode)
            {
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=request_noop|mode=" + mode.ToString()
                    + "|causality=none|write=none|trigger=" + trigger);
                return false;
            }
            ClearPendingRequest();
            try
            {
                _setDebugRendering(mode, true);
            }
            catch (Exception exception)
            {
                HandleRequestFailure(
                    mode,
                    trigger,
                    purpose,
                    emergencyReset,
                    exception);
                return false;
            }

            _requestPending = true;
            _pendingMode = mode;
            _pendingPreviousMode = previousMode;
            _pendingPollsRemaining = AcceptancePollLimit;
            _pendingTrigger = trigger;
            _pendingEmergencyReset = emergencyReset;
            _pendingPurpose = purpose;
            LogInfo(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=request_queued|acceptance=pending|mode="
                + mode.ToString()
                + "|from=" + previousMode.ToString()
                + "|force=true|trigger=" + trigger);
            bool completed = ObservePendingAcceptance();
            if (_requestPending && IsActivationPurpose(purpose))
            {
                // The pinned SHCDE-SE dispatcher executes immediately when
                // called from this Unity Update lane. Waiting across frames
                // would make unload/rollback race a still-queued mode 1/5
                // write. Fence any non-attested deferred topology now by
                // putting the owned baseline behind that request in the same
                // dispatcher FIFO. Equality with the current baseline remains
                // explicitly unconfirmed.
                FailUnobservedActivationRequest(
                    mode,
                    previousMode,
                    trigger);
                return false;
            }
            return completed;
        }

        private bool ObservePendingAcceptance()
        {
            int? observed;
            try
            {
                observed = _readDebugRendering();
            }
            catch (Exception exception)
            {
                HandlePendingFailure(
                    "readback_failed",
                    exception);
                return false;
            }

            if (observed.HasValue)
            {
                _observedMode = observed.Value;
            }
            if (observed.HasValue && observed.Value == _pendingMode)
            {
                if (_pendingPreviousMode == _pendingMode)
                {
                    // Equality with the pre-request value cannot acknowledge a
                    // dispatcher action. Keep it pending rather than inventing
                    // causality from a value that was already present.
                    return ContinuePending(observed);
                }
                int mode = _pendingMode;
                int previousMode = _pendingPreviousMode;
                string trigger = _pendingTrigger;
                bool emergencyReset = _pendingEmergencyReset;
                PendingPurpose purpose = _pendingPurpose;
                ClearPendingRequest();
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=mode_transition_observed|from="
                    + previousMode.ToString()
                    + "|mode=" + mode.ToString()
                    + "|source=GameMap.DebugLayerRendering|trigger="
                    + trigger
                    + "|request="
                    + (emergencyReset ? "emergency_reset" : "normal")
                    + "|causality=state_change"
                    + "|render_completion=unverified");
                return CompleteObservedTransition(purpose, trigger, mode);
            }

            if (observed.HasValue
                && observed.Value != _pendingPreviousMode)
            {
                int expectedMode = _pendingMode;
                string trigger = _pendingTrigger;
                ClearPendingRequest();
                HandleOwnershipDeviation(
                    trigger,
                    observed.Value,
                    expectedMode);
                return false;
            }
            return ContinuePending(observed);
        }

        private void HandleRequestFailure(
            int mode,
            string trigger,
            PendingPurpose purpose,
            bool emergencyReset,
            Exception exception)
        {
            RecordFailure(trigger + "_request", exception);
            if (!emergencyReset)
            {
                RestoreOwnedMode(trigger + "_emergency_restore", true);
                return;
            }
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=reset_request_failed|mode=" + mode.ToString()
                + "|force=true|trigger=" + trigger
                + "|purpose=" + purpose.ToString());
        }

        private void HandlePendingFailure(
            string status,
            Exception exception)
        {
            int mode = _pendingMode;
            string trigger = _pendingTrigger;
            bool emergencyReset = _pendingEmergencyReset;
            PendingPurpose purpose = _pendingPurpose;
            ClearPendingRequest();
            RecordFailure(trigger + "_" + status, exception);
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=request_unconfirmed|mode=" + mode.ToString()
                + "|trigger=" + trigger
                + "|cause=" + status);
            if (IsActivationPurpose(purpose))
            {
                QueueFifoCompensation(
                    mode,
                    trigger + "_" + status + "_fifo_compensation");
                return;
            }
            if (!emergencyReset)
            {
                RestoreOwnedMode(trigger + "_emergency_restore", true);
                return;
            }
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=reset_unconfirmed|mode=-1|trigger="
                + trigger
                + "|purpose=" + purpose.ToString());
        }

        private bool ContinuePending(int? observed)
        {
            _pendingPollsRemaining--;
            if (_pendingPollsRemaining > 0)
            {
                if (_pendingPollsRemaining == AcceptancePollLimit - 1)
                {
                    LogInfo(
                        "SEDE_RUNTIME_V1|event=building_placement_grid"
                        + "|status=request_pending|mode="
                        + _pendingMode.ToString()
                        + "|from=" + _pendingPreviousMode.ToString()
                        + "|observed=" + DescribeMode(observed)
                        + "|remaining_polls="
                        + _pendingPollsRemaining.ToString()
                        + "|trigger=" + _pendingTrigger);
                }
                return false;
            }

            HandlePendingFailure(
                "acceptance_timeout",
                new TimeoutException(
                    "GameMap.DebugLayerRendering did not transition from "
                    + _pendingPreviousMode.ToString()
                    + " to " + _pendingMode.ToString()
                    + "; observed " + DescribeMode(observed)));
            return false;
        }

        private bool CompleteObservedTransition(
            PendingPurpose purpose,
            string trigger,
            int mode)
        {
            switch (purpose)
            {
            case PendingPurpose.SelectStructureLayer:
                if (!_ownershipClaimed || mode != StructureLayerMode)
                {
                    return FailTransitionInvariant(
                        "Structure-layer transition completed without its ownership claim");
                }
                return RequestMode(
                    ActivatorMode,
                    "ctrl_alt_g_activator",
                    PendingPurpose.ActivateStructureLayer,
                    false,
                    StructureLayerMode);

            case PendingPurpose.ActivateStructureLayer:
                if (!_ownershipClaimed || mode != ActivatorMode)
                {
                    return FailTransitionInvariant(
                        "Activator transition completed without its ownership claim");
                }
                _activationSequenceObserved = true;
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=activation_sequence_observed"
                    + "|sequence=-1,1,5|terminal_mode=5"
                    + "|ownership=claimed"
                    + "|render_completion=unverified");
                return true;

            case PendingPurpose.RestoreOwnedBaseline:
                if (!_ownershipClaimed || mode != _ownedBaselineMode)
                {
                    return FailTransitionInvariant(
                        "Baseline transition completed without its ownership claim");
                }
                ReleaseOwnership();
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=owned_baseline_observed|mode="
                    + mode.ToString()
                    + "|ownership=released"
                    + "|render_completion=unverified|trigger=" + trigger);
                return true;

            default:
                return FailTransitionInvariant(
                    "Observed grid transition has no pending purpose");
            }
        }

        private bool RestoreOwnedMode(string trigger, bool emergencyReset)
        {
            if (!_ownershipClaimed)
            {
                return false;
            }

            if (_requestPending)
            {
                return ObservePendingAcceptance();
            }

            if (_fifoCompensationQueued)
            {
                return AuditFifoCompensation(trigger, true);
            }

            int? observed;
            try
            {
                observed = _readDebugRendering();
            }
            catch (Exception exception)
            {
                HandleOwnershipUncertain(trigger, exception);
                return false;
            }
            if (!observed.HasValue)
            {
                HandleOwnershipUncertain(
                    trigger,
                    new InvalidOperationException(
                        "GameMap.instance exposes no current debug mode"));
                return false;
            }
            _observedMode = observed.Value;

            if (observed.Value == _ownedBaselineMode)
            {
                // No write and no claim that a request succeeded: the baseline
                // is merely what is observable now. This is the safe outcome
                // after a refused first-stage request.
                ClearPendingRequest();
                ReleaseOwnership();
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=owned_baseline_already_observed|mode="
                    + observed.Value.ToString()
                    + "|causality=none|write=none|ownership=released"
                    + "|trigger=" + trigger);
                return true;
            }

            bool ownsObservedMode = _activationSequenceObserved
                ? observed.Value == ActivatorMode
                : observed.Value == StructureLayerMode
                    || observed.Value == ActivatorMode;
            if (!ownsObservedMode)
            {
                HandleOwnershipDeviation(
                    trigger,
                    observed.Value,
                    _activationSequenceObserved
                        ? ActivatorMode
                        : StructureLayerMode);
                return false;
            }

            return RequestMode(
                _ownedBaselineMode,
                trigger,
                PendingPurpose.RestoreOwnedBaseline,
                emergencyReset,
                observed.Value);
        }

        private void HandleOwnershipDeviation(
            string trigger,
            int observedMode,
            int expectedMode)
        {
            ClearPendingRequest();
            ReleaseOwnership();
            RecordFailure(
                trigger + "_ownership_lost",
                new InvalidOperationException(
                    "Owned debug mode changed from expected "
                    + expectedMode.ToString()
                    + " to foreign " + observedMode.ToString()));
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=ownership_lost|expected="
                + expectedMode.ToString()
                + "|observed=" + observedMode.ToString()
                + "|write=none|ownership=released|trigger=" + trigger);
        }

        private void HandleOwnershipUncertain(
            string trigger,
            Exception exception)
        {
            ClearPendingRequest();
            ReleaseOwnership();
            RecordFailure(trigger + "_ownership_unverifiable", exception);
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=ownership_unverifiable|write=none"
                + "|ownership=released|trigger=" + trigger);
        }

        private void ReleaseOwnership()
        {
            _ownershipClaimed = false;
            _activationSequenceObserved = false;
            _ownedBaselineMode = DisabledMode;
            ClearFifoCompensationTracking();
        }

        private void ClearFifoCompensationTracking()
        {
            _fifoCompensationQueued = false;
            _fifoCompensationPrecursorMode = DisabledMode;
            _fifoCompensationPrecursorObserved = false;
            _fifoCompensationDeviationObserved = false;
        }

        private static bool IsActivationPurpose(PendingPurpose purpose)
        {
            return purpose == PendingPurpose.SelectStructureLayer
                || purpose == PendingPurpose.ActivateStructureLayer;
        }

        private void FailUnobservedActivationRequest(
            int mode,
            int previousMode,
            string trigger)
        {
            ClearPendingRequest();
            RecordFailure(
                trigger + "_unsupported_deferred_dispatch",
                new InvalidOperationException(
                    "Pinned main-thread SetDebugRendering request did not "
                    + "transition GameMap.DebugLayerRendering from "
                    + previousMode.ToString() + " to " + mode.ToString()
                    + " before returning"));
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=request_unconfirmed|mode=" + mode.ToString()
                + "|trigger=" + trigger
                + "|cause=unsupported_deferred_dispatch");
            QueueFifoCompensation(
                mode,
                trigger + "_fifo_compensation");
        }

        private void QueueFifoCompensation(
            int unobservedMode,
            string trigger)
        {
            if (!_ownershipClaimed || _fifoCompensationQueued)
            {
                return;
            }

            int? before = _observedMode;
            _fifoCompensationQueued = true;
            _fifoCompensationPrecursorMode = unobservedMode;
            _fifoCompensationPrecursorObserved = false;
            _fifoCompensationDeviationObserved = false;
            try
            {
                // This deliberate same-value request is a FIFO fence, not an
                // acceptance claim: if mode 1/5 is still queued, -1 follows it;
                // if execution was swallowed, the already-observed baseline is
                // simply written again. The fence is admitted only from the
                // vanilla -1 baseline; later deviations never trigger a write
                // or qualify as a causal restore observation.
                _setDebugRendering(_ownedBaselineMode, true);
            }
            catch (Exception exception)
            {
                RecordFailure(trigger + "_request", exception);
                LogError(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=fifo_compensation_failed|mode="
                    + _ownedBaselineMode.ToString()
                    + "|for_unobserved_mode=" + unobservedMode.ToString()
                    + "|ownership=retained|trigger=" + trigger);
                return;
            }

            LogInfo(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=fifo_compensation_queued|mode="
                + _ownedBaselineMode.ToString()
                + "|for_unobserved_mode=" + unobservedMode.ToString()
                + "|acceptance=unverified|causality=fifo_fence"
                + "|ownership=retained|trigger=" + trigger);

            ObserveFifoCompensation(before, trigger, false);
        }

        private bool AuditFifoCompensation(
            string trigger,
            bool retryObservedPrecursor)
        {
            int? before = _observedMode;
            return ObserveFifoCompensation(
                before,
                trigger,
                retryObservedPrecursor);
        }

        private bool ObserveFifoCompensation(
            int? before,
            string trigger,
            bool retryObservedPrecursor)
        {
            int? observed;
            try
            {
                observed = _readDebugRendering();
            }
            catch (Exception exception)
            {
                RecordFailure(
                    trigger + "_fifo_compensation_readback",
                    exception);
                LogError(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=fifo_compensation_unverifiable|write=none"
                    + "|ownership=retained|trigger=" + trigger);
                return false;
            }
            if (!observed.HasValue)
            {
                RecordFailure(
                    trigger + "_fifo_compensation_readback",
                    new InvalidOperationException(
                        "GameMap.instance exposes no current debug mode"));
                LogError(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=fifo_compensation_unverifiable|write=none"
                    + "|ownership=retained|trigger=" + trigger);
                return false;
            }

            _observedMode = observed.Value;
            if (observed.Value == _fifoCompensationPrecursorMode)
            {
                _fifoCompensationPrecursorObserved = true;
            }
            else if (observed.Value != _ownedBaselineMode
                && observed.Value != StructureLayerMode)
            {
                _fifoCompensationDeviationObserved = true;
            }
            bool causalOwnedPrevious = before.HasValue
                && (before.Value == StructureLayerMode
                    || before.Value == _fifoCompensationPrecursorMode);
            if (observed.Value == _ownedBaselineMode
                && causalOwnedPrevious
                && !_fifoCompensationDeviationObserved)
            {
                int baseline = _ownedBaselineMode;
                int previous = before.HasValue
                    ? before.Value
                    : _fifoCompensationPrecursorMode;
                ReleaseOwnership();
                LogInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=mode_transition_observed|from="
                    + previous.ToString()
                    + "|mode=" + baseline.ToString()
                    + "|source=GameMap.DebugLayerRendering"
                    + "|request=fifo_compensation"
                    + "|causality=state_change"
                    + "|ownership=released"
                    + "|render_completion=unverified|trigger=" + trigger);
                return true;
            }

            bool observedOwnedPrecursor =
                !_fifoCompensationDeviationObserved
                && (observed.Value == StructureLayerMode
                    || observed.Value == _fifoCompensationPrecursorMode);
            if (retryObservedPrecursor && observedOwnedPrecursor)
            {
                return RetryObservedFifoCompensation(
                    observed.Value,
                    trigger);
            }

            LogInfo(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=fifo_compensation_drain_unverified"
                + "|observed=" + observed.Value.ToString()
                + "|precursor_observed="
                + (_fifoCompensationPrecursorObserved ? "true" : "false")
                + "|deviation_observed="
                + (_fifoCompensationDeviationObserved ? "true" : "false")
                + "|causality=unverified|write=none"
                + "|ownership=retained|trigger=" + trigger);
            return false;
        }

        private bool RetryObservedFifoCompensation(
            int observedOwnedMode,
            string trigger)
        {
            int precursor = _fifoCompensationPrecursorMode;
            ClearFifoCompensationTracking();
            LogInfo(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=fifo_compensation_retry_queued"
                + "|from=" + observedOwnedMode.ToString()
                + "|mode=" + _ownedBaselineMode.ToString()
                + "|for_unobserved_mode=" + precursor.ToString()
                + "|retry=1|retry_limit=1"
                + "|ownership=retained|trigger=" + trigger);
            return RequestMode(
                _ownedBaselineMode,
                trigger + "_fifo_retry",
                PendingPurpose.RestoreOwnedBaseline,
                true,
                observedOwnedMode);
        }

        private bool DrainTerminalRestore(string trigger)
        {
            int pollsRemaining = AcceptancePollLimit * 2;
            while (_requestPending && pollsRemaining > 0)
            {
                pollsRemaining--;
                ObservePendingAcceptance();
            }
            if (_requestPending)
            {
                int mode = _pendingMode;
                ClearPendingRequest();
                RecordFailure(
                    trigger + "_terminal_drain_budget",
                    new TimeoutException(
                        "Terminal restore drain exhausted its bounded poll budget"));
                LogError(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=terminal_restore_budget_exhausted"
                    + "|mode=" + mode.ToString()
                    + "|poll_limit="
                    + (AcceptancePollLimit * 2).ToString()
                    + "|ownership=retained|trigger=" + trigger);
            }

            bool complete = !_ownershipClaimed && !_requestPending;
            string message =
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=terminal_restore_"
                + (complete ? "complete" : "unconfirmed")
                + "|observed=" + DescribeMode(_observedMode)
                + "|request_pending="
                + (_requestPending ? "true" : "false")
                + "|ownership="
                + (_ownershipClaimed ? "retained" : "released")
                + "|poll_budget="
                + (AcceptancePollLimit * 2).ToString()
                + "|trigger=" + trigger;
            if (complete)
            {
                LogInfo(message);
            }
            else
            {
                LogError(message);
            }
            return complete;
        }

        private bool FailTransitionInvariant(string message)
        {
            RecordFailure(
                "transition_invariant",
                new InvalidOperationException(message));
            RestoreOwnedMode(
                "transition_invariant_emergency_restore",
                true);
            return false;
        }

        private void ClearPendingRequest()
        {
            _requestPending = false;
            _pendingMode = DisabledMode;
            _pendingPreviousMode = DisabledMode;
            _pendingPollsRemaining = 0;
            _pendingTrigger = null;
            _pendingEmergencyReset = false;
            _pendingPurpose = PendingPurpose.None;
        }

        private void RecordFailure(string trigger, Exception exception)
        {
            Exception cause = exception;
            while (cause is TargetInvocationException
                && cause.InnerException != null)
            {
                cause = cause.InnerException;
            }
            string summary = trigger + ": "
                + cause.GetType().Name + ": " + cause.Message;
            if (!_failed)
            {
                _failure = summary;
            }
            else if (string.IsNullOrEmpty(_failure))
            {
                _failure = summary;
            }
            else
            {
                _failure += "; " + summary;
            }
            _failed = true;
            _mapActive = false;
            LogError(
                "SEDE_RUNTIME_V1|event=building_placement_grid"
                + "|status=failed_closed|trigger=" + trigger
                + "|reason=" + summary);
        }

        private static string DescribeMode(int? mode)
        {
            return mode.HasValue
                ? mode.Value.ToString()
                : "unavailable";
        }

        private void LogInfo(string message)
        {
            try
            {
                _info(message);
            }
            catch
            {
                // Logging must never make an already-safe graphics toggle unsafe.
            }
        }

        private void LogError(string message)
        {
            try
            {
                _error(message);
            }
            catch
            {
                // The fail-closed state and ownership decision are authoritative.
            }
        }
    }
}
