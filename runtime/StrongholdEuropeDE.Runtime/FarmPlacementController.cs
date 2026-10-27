using System;
using System.Globalization;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Buildings;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Lifts Crusader's "food farms only on fertile ground" rule to the Stronghold 1
    /// rule, by answering the extender's placement-validation event ourselves.
    /// </summary>
    /// <remarks>
    /// Placement lives in the native engine - Assembly-CSharp only forwards
    /// coordinates through <c>DLL_MapAction</c> - so Harmony cannot reach the check.
    /// The script extender detours the native validator and offers the verdict for
    /// override: setting <see cref="BuildingPlacementValidationEventArgs.CustomValidationRules"/>
    /// makes it write <see cref="BuildingPlacementValidationEventArgs.ForceBlockPlacementState"/>
    /// into the tile manager after the original ran
    /// (SHCDESE.Detours/BulkBuildingDetours.cs:417-433).
    ///
    /// We answer in both directions, never only permissively. The validator receives
    /// one tile per call, and the engine's aggregation across a farm's footprint is
    /// not visible from the decompiled sources - so a handler that only ever wrote
    /// "allowed" could clear a block another tile had earned. Answering every farm
    /// tile with our own complete verdict keeps the outcome consistent whichever way
    /// the engine aggregates.
    /// </remarks>
    internal sealed class FarmPlacementController
    {
        private readonly Action<string> _info;
        private readonly Action<string> _error;

        private IDisposable _subscription;
        private bool _failed;
        private long _allowed;
        private long _blocked;
        private bool _firstDecisionLogged;

        // The event route alone does not move the engine: a session logged
        // allowed=180 / blocked=441 with accepted=True on grass, and the game
        // still refused. The extender writes our verdict into
        // TileManager.IsPlacementBlocked and then returns the *native*
        // trampoline result unchanged - and the caller evidently reads the
        // return value. So we also postfix the detour itself and correct the
        // result, while logging the original for the first few decisions so the
        // encoding is measured rather than assumed.
        private const int ResultSamplesToLog = 24;
        private static FarmPlacementController _current;
        private int _resultSamplesLogged;
        private bool _lastVerdictAccepted;
        private bool _lastVerdictValid;

        internal FarmPlacementController(Action<string> info, Action<string> error)
        {
            if (info == null)
            {
                throw new ArgumentNullException("info");
            }
            if (error == null)
            {
                throw new ArgumentNullException("error");
            }
            _info = info;
            _error = error;
        }

        internal bool Failed
        {
            get { return _failed; }
        }

        internal long AllowedCount
        {
            get { return _allowed; }
        }

        internal long BlockedCount
        {
            get { return _blocked; }
        }

        internal void Subscribe()
        {
            if (_subscription != null)
            {
                throw new InvalidOperationException(
                    "Farm placement rule is already subscribed");
            }
            Observable<BuildingPlacementValidationEventArgs> stream =
                BuildingR3EventHooks.OnPlacementValidation.Observable;
            if (stream == null)
            {
                throw new InvalidOperationException(
                    "Script extender exposes no placement-validation stream");
            }
            _subscription = ObservableSubscribeExtensions.Subscribe(stream, OnValidate);
            _current = this;
        }

        /// <summary>
        /// Corrects the native validator's return value for a tile our rule
        /// accepted. Called from the Harmony postfix on the extender detour.
        /// </summary>
        /// <remarks>
        /// The native encoding is not documented anywhere we can read, so the
        /// first <see cref="ResultSamplesToLog"/> decisions are logged with the
        /// original value next to our verdict. That turns the next session into
        /// a measurement instead of another guess. The measured placeable state
        /// is used only after our complete predicate positively identifies safe
        /// land; every other verdict preserves the native result.
        /// </remarks>
        internal void CorrectValidationResult(ref long result)
        {
            if (_failed || !_lastVerdictValid)
            {
                return;
            }
            bool accepted = _lastVerdictAccepted;
            _lastVerdictValid = false;
            if (_resultSamplesLogged < ResultSamplesToLog)
            {
                _resultSamplesLogged++;
                _info(
                    "Farm placement native result=" + result.ToString(
                        CultureInfo.InvariantCulture)
                    + " ourVerdict=" + (accepted ? "accept" : "block"));
            }
            // The result is a native state code, not a boolean. A 2026-08-11
            // run established 1 as a placeable state and led to a narrow 3->1
            // correction. Other measured sessions contain 2, 391 and 395 for
            // tiles positively accepted by the complete land predicate. The
            // narrow correction did nothing in those paths, so Crusader's
            // oasis-only decision survived.
            //
            // Normalize every positive Loosen decision to the measured
            // placeable state. Silent and Block decisions are passed through
            // byte-for-byte, and the global placement-block flag is still
            // never cleared here; unsafe footprint tiles therefore retain
            // both native and explicit blocking.
            result = FarmPlacementResultDecision.Normalize(result, accepted);
        }

        internal static void ValidatorPostfix(ref long __result)
        {
            FarmPlacementController controller = _current;
            if (controller != null)
            {
                controller.CorrectValidationResult(ref __result);
            }
        }

        internal void Rollback()
        {
            _current = null;
            IDisposable subscription = _subscription;
            _subscription = null;
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
                _error("Farm placement rule could not be detached: " + exception);
            }
        }

        private void OnValidate(BuildingPlacementValidationEventArgs e)
        {
            // The override is read after the trampoline but from the Pre-phase args,
            // so only the Pre event can change the verdict.
            if (e == null || e.Phase != EventHookPhase.Pre || _failed)
            {
                return;
            }
            if (!FarmPlacementRule.IsFoodFarm(e.Mappers))
            {
                return;
            }
            try
            {
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                // Bereichspruefung VOR GetTileId, wie es die Hafenbahn seit dem
                // 15.08. tut (DockPlacementController.cs:309-312). GetTileId
                // indiziert MapRowLookupTable[3*tileY] ohne eigene Schranke
                // (GameTileManagerAPI.cs:319-322), und IsValidTileId prueft nur
                // 0 <= id < 640000 - ein Muellwert besteht diese Pruefung fast
                // immer und liefert dann die Flags einer FREMDEN Kachel. Genau
                // darauf haette die Regel dann geantwortet.
                if (!tiles.IsTileInsideMapBounds(e.TileX, e.TileY))
                {
                    return;
                }
                int tileId = tiles.GetTileId(e.TileX, e.TileY);
                if (!tiles.IsValidTileId(tileId))
                {
                    return;
                }
                FarmPlacementRule.Verdict verdict = FarmPlacementRule.Judge(
                    tiles.GetTilePropertyFlag(tileId),
                    tiles.GetTileType(tileId));
                bool accepted = verdict == FarmPlacementRule.Verdict.Loosen;
                // Nur sperren, nie freigeben - der Kern der Behebung vom
                // 15.08.2026.
                //
                // Der Ereigniskanal wirkt auf die GANZE Grundflaeche, die
                // Detour liefert aber EINE Kachel je Aufruf
                // (BulkBuildingDetours.cs:417-433). Ein
                // ForceBlockPlacementState=false auf der Ankerkachel loeschte
                // deshalb das native Urteil ueber alle uebrigen Kacheln mit:
                // Anker auf Gras, Rest im Wasser - Farm im Wasser. Genau das
                // hat der Nutzer gemeldet, und im Protokoll stand dazu
                // 24 von 24 "native result=3 ourVerdict=accept".
                //
                // Erlaubt wird ausschliesslich ueber den Rueckgabewert
                // (Normalisierung auf den kanonischen Erfolgswert 1 im
                // Postfix); dort gilt das Urteil nur fuer diese eine Kachel.
                // Die Hafenregel macht es seit dem 15.08. genauso, und aus
                // demselben Grund.
                //
                // Und gesperrt wird nur bei NACHGEWIESENEM Hindernis. Bis zum
                // 16.08.2026 sperrte jedes "nicht angenommen" - also auch
                // jede Kachel, ueber die die Regel schlicht nichts wusste. Das
                // ist die gefaehrliche Richtung und war die Ursache dafuer,
                // dass Farmen nur noch auf die Oase passten.
                if (verdict == FarmPlacementRule.Verdict.Block)
                {
                    e.CustomValidationRules = true;
                    e.ForceBlockPlacementState = true;
                }
                _lastVerdictAccepted = accepted;
                _lastVerdictValid = true;
                if (accepted)
                {
                    _allowed++;
                }
                else
                {
                    _blocked++;
                }
                if (!_firstDecisionLogged)
                {
                    // Flags und Kacheltyp gehoeren in die Zeile, nicht nur das
                    // Urteil. Der Wasserfehler vom 15.08. war im Protokoll
                    // unsichtbar: 24 Zeilen "ourVerdict=accept" ohne eine
                    // einzige Angabe, WORAUF geantwortet wurde. Die Hafenbahn
                    // schreibt flags und type mit, und nur deshalb war dort in
                    // einem Lauf klar, was die Regel sieht.
                    _firstDecisionLogged = true;
                    _info(
                        "Farm placement rule answered its first tile: mapper="
                        + e.Mappers + " tile=" + e.TileX + "," + e.TileY
                        + " flags=0x" + ((uint)tiles.GetTilePropertyFlag(tileId)).ToString("X8")
                        + " type=0x" + ((byte)tiles.GetTileType(tileId)).ToString("X2")
                        + " accepted=" + accepted);
                }
            }
            catch (Exception exception)
            {
                // Never leave a half-applied verdict behind: hand the tile back to
                // the engine and stay out of the way for the rest of the session.
                _failed = true;
                e.CustomValidationRules = false;
                e.ForceBlockPlacementState = true;
                _error(
                    "Farm placement rule failed closed; the Crusader rule applies again: "
                    + exception);
            }
        }
    }
}
