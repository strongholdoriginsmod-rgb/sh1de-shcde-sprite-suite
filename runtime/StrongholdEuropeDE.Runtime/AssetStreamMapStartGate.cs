namespace StrongholdEuropeDE.Runtime
{
    internal enum AssetStreamMapGateAction
    {
        None = 0,
        EndOldToVanilla = 1,
        BeginEpoch = 2,
    }

    /// <summary>
    /// Dependency-free pairing for SHCDE-SE's exact load/save/start detours.
    /// A top-level Load PRE begins the new epoch. Nested load/save calls and
    /// their old-map Unload notifications stay inside that same epoch; Start
    /// PRE is the fallback for native flows without a managed Load event.
    /// </summary>
    internal sealed class AssetStreamMapStartGate
    {
        private int _mapLoadDepth;
        private int _saveLoadDepth;
        private int _startDepth;
        private bool _epochBegun;

        internal AssetStreamMapGateAction OnMapLoadPre(bool baselineComplete)
        {
            return OnLoadPre(ref _mapLoadDepth, baselineComplete);
        }

        internal AssetStreamMapGateAction OnSaveLoadPre(bool baselineComplete)
        {
            bool nested = AnyPairOpen;
            _saveLoadDepth++;
            if (nested)
            {
                return AssetStreamMapGateAction.None;
            }

            // A top-level save load replaces the native map even though its
            // Unload notifications are nested inside the LoadSave PRE/POST
            // pair.  Those nested notifications must stay ignored, but the
            // old streamed ownership must not survive the replacement.  A
            // BeginEpoch action deliberately means start-or-rollover to the
            // runtime lane: it ends the active epoch before beginning the new
            // one.  Nested MapLoad/LoadSave callbacks then share that new
            // epoch and cannot request a second rollover.
            _epochBegun = baselineComplete;
            return baselineComplete
                ? AssetStreamMapGateAction.BeginEpoch
                : AssetStreamMapGateAction.EndOldToVanilla;
        }

        internal void OnMapLoadPost()
        {
            if (_mapLoadDepth > 0)
            {
                _mapLoadDepth--;
            }
        }

        internal void OnSaveLoadPost()
        {
            if (_saveLoadDepth > 0)
            {
                _saveLoadDepth--;
            }
        }

        internal AssetStreamMapGateAction OnStartPre(bool baselineComplete)
        {
            bool nested = AnyPairOpen;
            _startDepth++;
            if (nested) return AssetStreamMapGateAction.None;
            if (_epochBegun)
            {
                return AssetStreamMapGateAction.None;
            }
            if (baselineComplete)
            {
                _epochBegun = true;
                return AssetStreamMapGateAction.BeginEpoch;
            }
            return AssetStreamMapGateAction.EndOldToVanilla;
        }

        internal AssetStreamMapGateAction OnBaselineCompleted()
        {
            if (!AnyPairOpen || _epochBegun)
            {
                return AssetStreamMapGateAction.None;
            }
            _epochBegun = true;
            return AssetStreamMapGateAction.BeginEpoch;
        }

        /// <summary>
        /// SHCDE 2.80 can enter the map editor without exposing a matching
        /// Load/Start PRE pair to this lane. The editor-ready state is an
        /// independent, stable map boundary and may therefore open the one
        /// missing epoch after all sprite baselines are rooted.
        /// </summary>
        internal AssetStreamMapGateAction OnEditorReady(bool baselineComplete)
        {
            if (!baselineComplete || _epochBegun)
            {
                return AssetStreamMapGateAction.None;
            }
            _epochBegun = true;
            return AssetStreamMapGateAction.BeginEpoch;
        }

        /// <summary>
        /// Second editor fallback (2026-09-02). A GM sprite request can only
        /// come from a map being drawn. When the baselines are rooted and no
        /// lifecycle event has opened an epoch, the request itself is the map
        /// boundary. Nested load pairs and an already begun epoch are left
        /// alone exactly like OnEditorReady.
        /// </summary>
        internal AssetStreamMapGateAction OnSpriteRequest(bool baselineComplete)
        {
            if (!baselineComplete || _epochBegun)
            {
                return AssetStreamMapGateAction.None;
            }
            _epochBegun = true;
            return AssetStreamMapGateAction.BeginEpoch;
        }

        internal void OnStartPost()
        {
            if (_startDepth > 0)
            {
                _startDepth--;
            }
        }

        internal bool IgnoreNestedUnload
        {
            get { return AnyPairOpen; }
        }

        internal bool EpochBegun
        {
            get { return _epochBegun; }
        }

        internal void OnExternalUnload()
        {
            Reset();
        }

        internal void Reset()
        {
            _mapLoadDepth = 0;
            _saveLoadDepth = 0;
            _startDepth = 0;
            _epochBegun = false;
        }

        private AssetStreamMapGateAction OnLoadPre(
            ref int ownDepth,
            bool baselineComplete)
        {
            bool nested = AnyPairOpen;
            ownDepth++;
            if (nested)
            {
                return AssetStreamMapGateAction.None;
            }
            if (_epochBegun)
            {
                // An ordinary MapLoad can be a nested part of a map-start
                // sequence whose epoch already began. SaveLoad has its own
                // top-level rollover path above because it nests the old-map
                // Unload event inside the replacement operation.
                return AssetStreamMapGateAction.None;
            }
            _epochBegun = baselineComplete;
            return baselineComplete
                ? AssetStreamMapGateAction.BeginEpoch
                : AssetStreamMapGateAction.EndOldToVanilla;
        }

        private bool AnyPairOpen
        {
            get
            {
                return _mapLoadDepth > 0
                    || _saveLoadDepth > 0
                    || _startDepth > 0;
            }
        }
    }
}
