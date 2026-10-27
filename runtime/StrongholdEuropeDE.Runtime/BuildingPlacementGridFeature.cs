using System;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.MapLoader;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Runtime adapter for the optional building-placement grid. The feature is
    /// disabled by default: subscription and map start are observational, and
    /// only a fresh Ctrl+Alt+G chord may request ownership. Ctrl+Alt+G is sampled
    /// only while the map lifecycle controller reports an active map. Unload,
    /// rollback and failure restore only proven owned state or queue a FIFO
    /// compensation behind an otherwise unobserved activation request.
    /// </summary>
    internal sealed class BuildingPlacementGridFeature
    {
        private readonly BuildingPlacementGridController _controller;
        private readonly Action<string> _info;
        private readonly Action<string> _error;
        private readonly Func<BuildingPlacementGridInputState> _readInput;

        private IDisposable _mapStartSubscription;
        private IDisposable _mapUnloadSubscription;

        internal BuildingPlacementGridFeature(
            Action<string> info,
            Action<string> error)
            : this(
                info,
                error,
                BuildingPlacementGridInputReflection.Bind(),
                BuildingPlacementGridReadbackReflection.Bind(
                    typeof(GameMap)))
        {
        }

        internal BuildingPlacementGridFeature(
            Action<string> info,
            Action<string> error,
            Func<BuildingPlacementGridInputState> readInput,
            Func<int?> readDebugRendering)
        {
            if (info == null)
            {
                throw new ArgumentNullException("info");
            }
            if (error == null)
            {
                throw new ArgumentNullException("error");
            }
            if (readInput == null)
            {
                throw new ArgumentNullException("readInput");
            }
            if (readDebugRendering == null)
            {
                throw new ArgumentNullException("readDebugRendering");
            }
            _info = info;
            _error = error;
            _readInput = readInput;
            Action<int, bool> setter = BuildingPlacementGridReflection.Bind(
                typeof(GameTileManagerAPI));
            _controller = new BuildingPlacementGridController(
                setter,
                readDebugRendering,
                info,
                error);
        }

        internal bool MapActive
        {
            get { return _controller.MapActive; }
        }

        internal bool StructureGridModeObserved
        {
            get { return _controller.StructureGridModeObserved; }
        }

        internal int? ObservedMode
        {
            get { return _controller.ObservedMode; }
        }

        internal bool RequestPending
        {
            get { return _controller.RequestPending; }
        }

        internal int? PendingMode
        {
            get { return _controller.PendingMode; }
        }

        internal bool Failed
        {
            get { return _controller.Failed; }
        }

        internal string Failure
        {
            get { return _controller.Failure; }
        }

        internal void Subscribe()
        {
            if (_mapStartSubscription != null
                || _mapUnloadSubscription != null
                || _controller.RolledBack)
            {
                throw new InvalidOperationException(
                    "Building placement grid is already subscribed or rolled back");
            }
            Observable<MapStartEventArgs> mapStart =
                MapLoaderR3EventHooks.OnStartMap.Observable;
            Observable<MapUnloadEventArgs> mapUnload =
                MapLoaderR3EventHooks.OnUnloadMap.Observable;
            if (mapStart == null || mapUnload == null)
            {
                throw new InvalidOperationException(
                    "Script extender exposes no exact map lifecycle streams");
            }

            IDisposable start = null;
            IDisposable unload = null;
            try
            {
                start = ObservableSubscribeExtensions.Subscribe(
                    mapStart,
                    OnStartMap);
                unload = ObservableSubscribeExtensions.Subscribe(
                    mapUnload,
                    OnUnloadMap);
                _mapStartSubscription = start;
                _mapUnloadSubscription = unload;
                start = null;
                unload = null;
                SafeInfo(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=ready|hotkey=Ctrl+Alt+G"
                    + "|default_state=disabled"
                    + "|activation=explicit_hotkey_only"
                    + "|layer_mode=1|activator_mode=5|off_mode=-1"
                    + "|ownership=vanilla_off_only"
                    + "|render_completion=unverified");
            }
            catch
            {
                _controller.Rollback();
                DisposeSubscription(start, "map start");
                DisposeSubscription(unload, "map unload");
                throw;
            }
        }

        internal void Tick()
        {
            try
            {
                _controller.PollPendingAcceptance();
                if (_controller.Failed
                    || _controller.RolledBack
                    || !_controller.MapActive
                    || _controller.RequestPending)
                {
                    return;
                }
                BuildingPlacementGridInputState input = _readInput();
                _controller.Tick(
                    input.ControlHeld,
                    input.AltHeld,
                    input.GPressedThisFrame);
            }
            catch (Exception exception)
            {
                FailClosedSafely("tick_unexpected", exception);
            }
        }

        internal bool Rollback()
        {
            bool terminalRestoreComplete = false;
            try
            {
                terminalRestoreComplete = _controller.Rollback();
            }
            catch (Exception exception)
            {
                FailClosedSafely("rollback_unexpected", exception);
            }
            IDisposable start = _mapStartSubscription;
            IDisposable unload = _mapUnloadSubscription;
            _mapStartSubscription = null;
            _mapUnloadSubscription = null;
            DisposeSubscription(start, "map start");
            DisposeSubscription(unload, "map unload");
            if (!terminalRestoreComplete)
            {
                SafeError(
                    "SEDE_RUNTIME_V1|event=building_placement_grid"
                    + "|status=rollback_terminal_unconfirmed"
                    + "|request_pending="
                    + (_controller.RequestPending ? "true" : "false")
                    + "|observed="
                    + (_controller.ObservedMode.HasValue
                        ? _controller.ObservedMode.Value.ToString()
                        : "unavailable"));
            }
            return terminalRestoreComplete;
        }

        private void OnStartMap(MapStartEventArgs value)
        {
            // Post is the first point at which the playable map is active.
            if (value == null || value.Phase != EventHookPhase.Post)
            {
                return;
            }
            try
            {
                _controller.OnMapStarted();
            }
            catch (Exception exception)
            {
                FailClosedSafely("map_start_callback", exception);
            }
        }

        private void OnUnloadMap(MapUnloadEventArgs value)
        {
            // Restore before native teardown only from causally owned state.
            // A previously queued FIFO compensation is audited without another
            // write or a false visual-cleanup claim.
            if (value == null || value.Phase != EventHookPhase.Pre)
            {
                return;
            }
            try
            {
                _controller.OnMapUnload();
            }
            catch (Exception exception)
            {
                FailClosedSafely("map_unload_callback", exception);
            }
        }

        private void FailClosedSafely(string trigger, Exception exception)
        {
            try
            {
                _controller.FailClosed(trigger, exception);
            }
            catch (Exception containmentFailure)
            {
                SafeError(
                    "Building placement grid containment failed during "
                    + trigger + ": " + containmentFailure);
            }
        }

        private void DisposeSubscription(
            IDisposable subscription,
            string label)
        {
            if (subscription == null)
            {
                return;
            }
            try
            {
                subscription.Dispose();
            }
            catch (Exception exception)
            {
                SafeError(
                    "Building placement grid could not detach from "
                    + label + ": " + exception);
            }
        }

        private void SafeInfo(string message)
        {
            try
            {
                _info(message);
            }
            catch
            {
                // Logging is not part of the graphics ownership contract.
            }
        }

        private void SafeError(string message)
        {
            try
            {
                _error(message);
            }
            catch
            {
                // Containment/rollback state is authoritative even if logging fails.
            }
        }
    }
}
