using System;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.Buildings;
using SHCDESE.EventAPI.MapLoader;
using SHCDESE.GameGlobals;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Misst, was der Hafen braucht - und setzt, wenn das Profil den
    /// Regelblock traegt, Wasserregel, Baukosten und Trefferpunkte um.
    /// </summary>
    /// <remarks>
    /// Der Wunsch lautet: der Hafen soll nur in Gewaesser passen, Geld kosten
    /// und Trefferpunkte haben. Ohne den generierten Regelblock
    /// (GeneratedDockRulesContract.Enabled = false) bleibt diese Bahn die
    /// reine Messbahn der Stufe 0 - sie liest und protokolliert, sonst nichts.
    ///
    /// MIT Regelblock kommen drei Stufen dazu, jede fail-closed:
    ///   1. WASSERREGEL: Fuer jede Hafenkachel ohne Wasserbefund wird das
    ///      Platzierungsereignis auf Sperren gestellt - dieselbe Kodierung,
    ///      mit der die Farmregel antwortet (FarmPlacementController). Auf
    ///      Wasserkacheln wird das Ereignis NICHT angefasst: eine Freigabe
    ///      von unserer Seite wuerde native Sperren (etwa
    ///      Gebaeudeueberlappung) loeschen, deren Regeln wir nie gemessen
    ///      haben. Wir verbieten nur, wir erlauben nie. Der Harmony-Postfix
    ///      bleibt ohne ref: der native Sperrcode des Hafens wurde nie
    ///      gemessen (nur die Annahme 107), ein erfundener Rueckgabewert
    ///      waere ein Ratespiel.
    ///   2. BAUKOSTEN: SetDefaultCost mit updateUnityEngineSite: false -
    ///      drittes Argument woertlich false, siehe die Warnung unten.
    ///   3. TREFFERPUNKTE: SetDefaultHealth, hinter dem Wachposten
    ///      BuildingHealthTableRVA != 0 (ein gescheiterter Muster-Scan
    ///      liesse 0 zurueck, GameGlobalsManager.cs).
    ///
    /// Die Werte (Holz, Gold, Trefferpunkte) sind SETZUNG des Profils, keine
    /// Messung; als Massstab gemessen am 14.08.2026: hovel=100, Struktur
    /// 108=300, Hafen vorher 0. Der Vorzustand wird einmal je Prozess
    /// gemerkt und bei Kartenende, Rollback und FailClosed per WERT
    /// zurueckgeschrieben - nicht ueber ClearOverrides, dessen Verhalten
    /// fuer einen per SetValue begonnenen Stapel mehrdeutig dokumentiert
    /// ist (Zhuqiaomon.xml: "Does NOT revert SetBase() changes"). Die
    /// Kostentabelle loescht der Extender bei OnUnloadMap ohnehin NICHT
    /// (GameBuildingManagerAPI.cs 316-318 nennt nur Health, Housing und
    /// FireDamage), die Ruecknahme muss also zwingend selbst geschehen.
    ///
    /// VERBOTEN FUER STRUCT_DOCK, dauerhaft und nachgerechnet:
    ///   SetGoldCost, SetWoodCost, SetStoneCost, SetIronIngotCost,
    ///   SetRawPitchCost und SetDefaultCost mit updateUnityEngineSite = true.
    /// Alle sechs laufen ueber GetCostVisualPtr bzw. SetCostVisual und rechnen
    /// die Unity-Schreibadresse als game_data_txt + (int)building * 20
    /// (GameBuildingManagerAPI.cs 1348-1368). GameData.game_data_txt ist
    /// new int[545] (GameData.cs 892, 1307) = 2180 Byte; 109 * 20 = 2180 zeigt
    /// exakt ein Element HINTER das Ende eines Objekts auf dem verwalteten
    /// Heap. Die einzige Schranke der Setzer prueft
    /// _buildingStoneCostsArray.Length, und die ist 237 * 20 = 4740, weil der
    /// Extender dort Elementzahl mit Bytezahl verwechselt (:267-268) - 545 < 4740,
    /// sie laesst durch. costVisualPtr.IsNull faengt es nicht, die Adresse ist
    /// gueltig und ungleich null. Das ist Heap-Korruption, und Heap-Korruption
    /// hat dieses Projekt schon zweimal lahmgelegt.
    /// Der einzige speichersichere Kosten-Setzer fuer 109 ist deshalb
    /// SetDefaultCost(..., updateUnityEngineSite: false) - das dritte Argument
    /// ausdruecklich false, die Vorgabe ist true. Nur er wird hier gerufen,
    /// und nur hinter der selbst gerechneten Schranke der Vorgabetabelle
    /// (im Spiel gemessen: entries=110, Index 109 ist der letzte Eintrag).
    ///
    /// Dieser Setzer schreibt aber nur die QUELLE. Am 15.08.2026 im Spiel
    /// gemessen: "Dock default cost after rules: Wood=20 ... Gold=30" neben
    /// "Dock live cost after rules: Wood=0 ... Gold=0" - der Hafen kostete
    /// nichts. Abgerechnet wird aus einer zweiten, verschraenkten Tabelle, die
    /// genau einmal je Prozess aus der Vorgabe gefuellt wird, lange bevor
    /// unsere Regel laeuft. Sie wird deshalb seit dem 15.08. unmittelbar
    /// beschrieben, ueber Marshal und ohne den Unity-Spiegel, den die sechs
    /// verbotenen Setzer mitfuehren. Begruendung, Schranke und Wachposten
    /// stehen bei WriteLiveCost.
    ///
    /// Die Bahn ist von der Farmbahn ueber die Mapper getrennt: die Farmregel
    /// antwortet nur fuer die Felder 70-73, diese Bahn sieht nur 195-198. Zwei
    /// Harmony-Postfixe auf derselben Detour sind zulaessig, solange das so
    /// bleibt. Wer die beiden Regler spaeter in einen gemeinsamen Zustandsplatz
    /// zusammenlegt, setzt die funktionierende Farmbahn aufs Spiel.
    /// </remarks>
    internal sealed class DockPlacementController
    {
        /// <summary>BuildingCost sind fuenf int mit Pack = 1 (BuildingCost.cs).</summary>
        private const ulong BuildingCostSize = 20UL;

        private const int TileSamplesToLog = 32;
        private const int ResultSamplesToLog = 8;

        // Nachschlagfrist nach dem Vorbild von UniversalSiegeCore
        // (init.lua 136-138: "One bounded retry covers missions that overwrite
        // map rules during their start phase") - nur dass hier gemessen wird:
        // lesen, vergleichen, ausschliesslich bei Abweichung erneut schreiben.
        private const int ReassertDelayMilliseconds = 1200;

        private readonly Action<string> _info;
        private readonly Action<string> _error;

        private IDisposable _placementSubscription;
        private IDisposable _mapStartSubscription;
        private IDisposable _mapUnloadSubscription;

        private bool _failed;
        private long _tiles;
        private long _waterTiles;
        private long _blockedTiles;
        private int _tileSamplesLogged;
        private int _resultSamplesLogged;
        private bool _measurementLogged;

        // Regelzustand der Stufen 2-3. Unter einer eigenen Sperre, weil
        // OnStartMap (R3-Abonnent), Tick (Unity-Update des Wirts) und
        // OnUnloadMap nicht belegt auf demselben Faden laufen (SEE Befund F);
        // die Sperre haelt Apply, Tick und Restore untereinander konsistent.
        private readonly object _rulesGate = new object();
        private bool _appliedThisMap;
        private bool _reassertPending;
        private int _reassertDueTick;

        // Vorzustand EINMAL JE PROZESS: static, damit auch eine erneute
        // Anwendung nach einem Kartenwechsel ohne Unload (Befund E: das
        // Unload-Ereignis feuert nur beim Rueckweg ins Menue) niemals unsere
        // eigenen Werte als "Original" einfaengt (SEE Abschnitt 6, Gefahr D).
        private static bool _originalCaptured;
        private static BuildingCost _originalCost;
        private static uint _originalHealth;

        // Der Vorzustand der ABGERECHNETEN Tabelle, getrennt gemerkt: sie ist
        // eine Kopie der Vorgabe, aber ab dem Kartenstart ein eigener Wert -
        // _originalCost aus GetDefaultCost taugt nicht als Ruecknahme fuer sie.
        // Erfasst wird erst, wenn alle Wachposten in WriteLiveCost bestanden
        // sind, also nie auf einer ungeprueften Adresse.
        private static bool _originalLiveCaptured;
        private static BuildingCost _originalLiveCost;

        // Vom Pre-Handler an den Postfix gereicht: nur so laesst sich der native
        // Rueckgabewert der Kachel zuordnen, die ihn erzeugt hat. Der Postfix
        // verbraucht das Kennzeichen bei jedem Durchlauf, damit eine Hafenkachel
        // niemals mit dem Ergebnis eines fremden Bauwerks gepaart wird.
        private static DockPlacementController _current;
        private bool _pendingSampleValid;
        private string _pendingSample;

        internal DockPlacementController(Action<string> info, Action<string> error)
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

        /// <summary>Hafenkacheln, die der Validierer uns gezeigt hat.</summary>
        internal long TileCount
        {
            get { return _tiles; }
        }

        /// <summary>Davon die, die nachweislich See oder Fluss tragen.</summary>
        internal long WaterTileCount
        {
            get { return _waterTiles; }
        }

        /// <summary>Kacheln, die die Wasserregel gesperrt hat (0 im Messmodus).</summary>
        internal long BlockedTileCount
        {
            get { return _blockedTiles; }
        }

        internal void Subscribe()
        {
            if (_placementSubscription != null
                || _mapStartSubscription != null
                || _mapUnloadSubscription != null)
            {
                throw new InvalidOperationException(
                    "Dock placement lane is already subscribed");
            }
            Observable<BuildingPlacementValidationEventArgs> placement =
                BuildingR3EventHooks.OnPlacementValidation.Observable;
            if (placement == null)
            {
                throw new InvalidOperationException(
                    "Script extender exposes no placement-validation stream");
            }
            Observable<MapStartEventArgs> mapStart =
                MapLoaderR3EventHooks.OnStartMap.Observable;
            if (mapStart == null)
            {
                throw new InvalidOperationException(
                    "Script extender exposes no map-start stream");
            }
            Observable<MapUnloadEventArgs> mapUnload =
                MapLoaderR3EventHooks.OnUnloadMap.Observable;
            if (mapUnload == null)
            {
                throw new InvalidOperationException(
                    "Script extender exposes no map-unload stream");
            }
            _placementSubscription =
                ObservableSubscribeExtensions.Subscribe(placement, OnValidate);
            _mapStartSubscription =
                ObservableSubscribeExtensions.Subscribe(mapStart, OnStartMap);
            // Pre wie beim Extender selbst (MapLoaderR3EventHooks.cs 18-19).
            // Befund E bleibt bestehen: dieses Ereignis feuert nur beim
            // Rueckweg ins Menue; bei Karte-zu-Karte-Wechseln setzt der
            // naechste OnStartMap idempotent neu, und der einmal je Prozess
            // gemerkte Vorzustand bleibt der einzig richtige.
            _mapUnloadSubscription =
                ObservableSubscribeExtensions.Subscribe(mapUnload, OnUnloadMap);
            _current = this;
        }

        internal void Rollback()
        {
            _current = null;
            // Erst die Werte zurueckgeben, dann abhaengen: deckt auch
            // ShutdownAndRollback mitten in der Sitzung (SEE Befund L).
            Restore("rollback");
            IDisposable placement = _placementSubscription;
            IDisposable mapStart = _mapStartSubscription;
            IDisposable mapUnload = _mapUnloadSubscription;
            _placementSubscription = null;
            _mapStartSubscription = null;
            _mapUnloadSubscription = null;
            DisposeSubscription(placement, "placement validation");
            DisposeSubscription(mapStart, "map start");
            DisposeSubscription(mapUnload, "map unload");
        }

        private void DisposeSubscription(IDisposable subscription, string what)
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
                _error(
                    "Dock placement lane could not be detached from "
                    + what + ": " + exception);
            }
        }

        /// <summary>
        /// Protokolliert den nativen Rueckgabewert neben unserem Befund.
        /// </summary>
        /// <remarks>
        /// Nur lesend - <paramref name="__result"/> wird nicht angefasst. Die
        /// Kodierung 3 = nicht baubar / 1 = baubar stammt aus einer Sitzung vom
        /// 11.08.2026 und gilt fuer die Farm; fuer den Hafen wurde bisher nur
        /// die Annahme (107) beobachtet, nie ein Sperrwert. Deshalb wird hier
        /// weiter gemessen statt korrigiert.
        /// </remarks>
        internal void ObserveValidationResult(long result)
        {
            if (_failed || !_pendingSampleValid)
            {
                return;
            }
            string sample = _pendingSample;
            _pendingSampleValid = false;
            _pendingSample = null;
            if (_resultSamplesLogged >= ResultSamplesToLog)
            {
                return;
            }
            _resultSamplesLogged++;
            _info(
                "Dock placement native result="
                + result.ToString(CultureInfo.InvariantCulture)
                + " " + sample);
        }

        internal static void ValidatorPostfix(long __result)
        {
            DockPlacementController controller = _current;
            if (controller != null)
            {
                controller.ObserveValidationResult(__result);
            }
        }

        private void OnValidate(BuildingPlacementValidationEventArgs e)
        {
            // Nur die Pre-Phase: der Ueberstimm-Kanal des Extenders liest die
            // Pre-Argumente nach dem Trampolin (BulkBuildingDetours.cs 417-433),
            // und nur in dieser Reihenfolge laesst sich der Postfix-Wert der
            // Kachel zuordnen.
            if (e == null || e.Phase != EventHookPhase.Pre || _failed)
            {
                return;
            }
            if (!DockPlacementRule.IsDock(e.Mappers))
            {
                return;
            }
            try
            {
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                // GetTileId indiziert MapRowLookupTable[3 * tileY] ungeprueft
                // (GameTileManagerAPI.cs 319-322). Deshalb zuerst die
                // Bereichspruefung, die es selbst nicht hat, und danach die
                // Pruefung des Ergebnisses - GetTilePropertyFlag greift ohne
                // eigene Schranke in LogicGrid (:385-388).
                if (!tiles.IsTileInsideMapBounds(e.TileX, e.TileY))
                {
                    return;
                }
                int tileId = tiles.GetTileId(e.TileX, e.TileY);
                if (!tiles.IsValidTileId(tileId))
                {
                    return;
                }
                TilePropertyFlag flags = tiles.GetTilePropertyFlag(tileId);
                TileType type = tiles.GetTileType(tileId);
                bool water = DockPlacementRule.IsWater(flags);
                _tiles++;
                if (water)
                {
                    _waterTiles++;
                }
                bool blocked = false;
                if (GeneratedDockRulesContract.Enabled && !water)
                {
                    // Wasserregel, nur in Richtung SPERREN - Kodierung
                    // woertlich von der Farmregel uebernommen
                    // (FarmPlacementController.cs 205-206). Auf Wasserkacheln
                    // wird das Ereignis nicht angefasst: der Ueberstimm-Kanal
                    // ueberschreibt das native Gesamturteil, und eine Freigabe
                    // von uns wuerde native Sperren loeschen, deren Regeln wir
                    // nicht kennen. Die Farm musste den Gesamtjob erben, weil
                    // sie ERLAUBT; wir verbieten nur.
                    e.CustomValidationRules = true;
                    e.ForceBlockPlacementState = true;
                    _blockedTiles++;
                    blocked = true;
                }
                string sample =
                    "tile=" + e.TileX.ToString(CultureInfo.InvariantCulture)
                    + "," + e.TileY.ToString(CultureInfo.InvariantCulture)
                    + " mapper=" + e.Mappers
                    + " flags=0x" + ((uint)flags).ToString(
                        "X8", CultureInfo.InvariantCulture)
                    + " type=0x" + ((byte)type).ToString(
                        "X2", CultureInfo.InvariantCulture)
                    + " water=" + (water ? "yes" : "no");
                if (GeneratedDockRulesContract.Enabled)
                {
                    sample += " verdict=" + (blocked ? "block" : "pass");
                }
                _pendingSample = sample;
                _pendingSampleValid = true;
                if (_tileSamplesLogged < TileSamplesToLog)
                {
                    _tileSamplesLogged++;
                    _info("Dock placement sample: " + sample);
                }
            }
            catch (Exception exception)
            {
                // Nie ein halb gesetztes Urteil zuruecklassen (woertlich wie
                // der Fehlerzweig der Farmregel): die Kachel geht zurueck an
                // die Engine, danach stellt sich die Bahn ab und gibt die
                // geschriebenen Werte zurueck.
                if (GeneratedDockRulesContract.Enabled)
                {
                    e.CustomValidationRules = false;
                    e.ForceBlockPlacementState = true;
                }
                FailClosed(exception);
            }
        }

        private void OnStartMap(MapStartEventArgs e)
        {
            // Post, weil erst danach die Karte steht.
            if (e == null || e.Phase != EventHookPhase.Post || _failed)
            {
                return;
            }
            // Die Messzeilen einmal je Sitzung: die Tabellen sind global, ein
            // zweiter Blick braechte nichts und jede Wiederholung macht das
            // Protokoll unlesbar.
            if (!_measurementLogged)
            {
                _measurementLogged = true;
                try
                {
                    GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                    _info("Dock default cost: " + ReadDefaultCost(buildings));
                    _info("Dock live cost: " + ReadLiveCost(buildings));
                    _info("Dock default health: " + ReadDefaultHealth(buildings));
                }
                catch (Exception exception)
                {
                    FailClosed(exception);
                }
            }
            if (_failed || !GeneratedDockRulesContract.Enabled)
            {
                return;
            }
            Apply();
        }

        private void OnUnloadMap(MapUnloadEventArgs e)
        {
            // Pre: bevor die Karte faellt, gehoeren die globalen Tabellen
            // wieder dem Spiel. Befund E: dieses Ereignis kommt nur auf dem
            // Rueckweg ins Menue; genau dort ist die Ruecknahme faellig.
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            lock (_rulesGate)
            {
                _reassertPending = false;
                Restore("map unload");
            }
        }

        /// <summary>
        /// Schreibt Kosten und Trefferpunkte des Hafens - einmal je Karte,
        /// hinter Wachposten, mit einmal je Prozess gemerktem Vorzustand.
        /// </summary>
        private void Apply()
        {
            lock (_rulesGate)
            {
                if (_failed || _appliedThisMap)
                {
                    return;
                }
                try
                {
                    string guardFailure = RuleTablesUnreachable();
                    if (guardFailure != null)
                    {
                        // Fail-closed OHNE zu schreiben: ein gescheiterter
                        // Muster-Scan hinterlaesst Adresse 0, und ein Schreiben
                        // relativ zu 0 waere das Ende der Sitzung.
                        FailClosed(new InvalidOperationException(guardFailure));
                        return;
                    }
                    GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                    if (!_originalCaptured)
                    {
                        _originalCost = buildings.GetDefaultCost(
                            DockPlacementRule.DockStruct);
                        _originalHealth = (uint)buildings.GetDefaultHealth(
                            DockPlacementRule.DockStruct);
                        _originalCaptured = true;
                        _info(
                            "Dock rules captured originals: cost="
                            + _originalCost.ToString()
                            + " health=" + _originalHealth.ToString(
                                CultureInfo.InvariantCulture));
                    }
                    WriteRuleValues(buildings);
                    _appliedThisMap = true;
                    _reassertDueTick = Environment.TickCount + ReassertDelayMilliseconds;
                    _reassertPending = true;
                    _info(
                        "Dock rules applied: wood="
                        + GeneratedDockRulesContract.WoodCost.ToString(
                            CultureInfo.InvariantCulture)
                        + " gold=" + GeneratedDockRulesContract.GoldCost.ToString(
                            CultureInfo.InvariantCulture)
                        + " health=" + GeneratedDockRulesContract.Health.ToString(
                            CultureInfo.InvariantCulture));
                }
                catch (Exception exception)
                {
                    FailClosed(exception);
                }
            }
        }

        /// <summary>
        /// Der 1200-ms-Nachschlag als Messung: lesen, vergleichen, nur bei
        /// Abweichung erneut schreiben - danach einmal Vorgabe- UND
        /// Live-Kostentabelle protokollieren (Propagationsmessung
        /// Default-&gt;Live fuer die naechste Sitzung).
        /// </summary>
        internal void Tick()
        {
            if (_failed || !GeneratedDockRulesContract.Enabled)
            {
                return;
            }
            lock (_rulesGate)
            {
                if (_failed || !_reassertPending)
                {
                    return;
                }
                // Vorzeichenrechnung uebersteht den TickCount-Ueberlauf.
                if (Environment.TickCount - _reassertDueTick < 0)
                {
                    return;
                }
                _reassertPending = false;
                try
                {
                    GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                    BuildingCost cost = buildings.GetDefaultCost(
                        DockPlacementRule.DockStruct);
                    int health = buildings.GetDefaultHealth(
                        DockPlacementRule.DockStruct);
                    bool unchanged =
                        cost.Wood == GeneratedDockRulesContract.WoodCost
                        && cost.Stone == 0
                        && cost.Iron == 0
                        && cost.Pitch == 0
                        && cost.Gold == GeneratedDockRulesContract.GoldCost
                        && health == (int)GeneratedDockRulesContract.Health;
                    if (unchanged)
                    {
                        _info("Dock rules reassert check: unchanged after 1200 ms");
                    }
                    else
                    {
                        // Etwas hat nach dem Kartenstart ueberschrieben - das
                        // ist die Messung, die dem USM-Vorbild fehlt (dessen
                        // "70/70" zaehlt nur gelungene Aufrufe, SEE Punkt K).
                        _info(
                            "Dock rules reassert check: foreign values cost="
                            + cost.ToString()
                            + " health=" + health.ToString(
                                CultureInfo.InvariantCulture)
                            + "; rewriting");
                        WriteRuleValues(buildings);
                    }
                    _info("Dock default cost after rules: " + ReadDefaultCost(buildings));
                    _info("Dock live cost after rules: " + ReadLiveCost(buildings));
                }
                catch (Exception exception)
                {
                    FailClosed(exception);
                }
            }
        }

        /// <summary>
        /// Gibt die einmal je Prozess gemerkten Originalwerte zurueck, falls
        /// in dieser Karte angewendet wurde. Wird von OnUnloadMap, Rollback
        /// und FailClosed gerufen.
        /// </summary>
        private void Restore(string trigger)
        {
            lock (_rulesGate)
            {
                if (!_appliedThisMap)
                {
                    return;
                }
                _appliedThisMap = false;
                _reassertPending = false;
                if (!_originalCaptured)
                {
                    // Apply erzwingt Capture vor dem ersten Schreiben; ohne
                    // Capture wurde nie geschrieben, es gibt nichts zu tun.
                    return;
                }
                try
                {
                    GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                    // Kosten zwingend selbst zuruecknehmen: der Extender
                    // loescht bei OnUnloadMap nur Health-, Housing- und
                    // FireDamage-Overrides (GameBuildingManagerAPI.cs 316-318),
                    // die Kostentabelle nicht. Health per WERT statt ueber den
                    // Override-Loescher des Extenders: dessen Verhalten ist
                    // fuer einen per SetValue begonnenen Stapel mehrdeutig
                    // dokumentiert (Zhuqiaomon.xml 1596-1623, Begruendung im
                    // Kopf der Datei); der gemerkte Wert ist gegen jede der
                    // moeglichen Stapelsemantiken korrekt.
                    buildings.SetDefaultCost(
                        DockPlacementRule.DockStruct,
                        _originalCost,
                        updateUnityEngineSite: false);
                    buildings.SetDefaultHealth(
                        DockPlacementRule.DockStruct,
                        _originalHealth);
                    RestoreLiveCost();
                    _info("Dock rules restored originals (" + trigger + ")");
                }
                catch (Exception exception)
                {
                    // Kein FailClosed von hier: Restore laeuft bereits aus
                    // FailClosed heraus, eine Schleife waere moeglich.
                    _error("Dock rules restore failed: " + exception);
                }
            }
        }

        /// <summary>
        /// Nimmt die abgerechnete Kostenzeile auf die gemerkten Werte zurueck.
        /// </summary>
        /// <remarks>
        /// Nur wenn WriteLiveCost bis zur Erfassung gekommen ist; dann sind
        /// Modul und Spaltenform dort bereits geprueft worden. Die Wachposten
        /// laufen hier trotzdem noch einmal, weil zwischen Anwendung und
        /// Ruecknahme ein Kartenwechsel liegt.
        /// </remarks>
        private void RestoreLiveCost()
        {
            if (!_originalLiveCaptured)
            {
                return;
            }
            NativeTable table;
            long[] columns;
            string failure = OpenLiveCostTable(out table, out columns);
            if (failure != null)
            {
                _error(failure + "; the live cost stays as it is.");
                return;
            }
            WriteRow(
                table,
                columns,
                (long)(int)DockPlacementRule.DockStruct,
                _originalLiveCost);
        }

        /// <summary>
        /// Schreibt die drei Regelwerte ueber die einzigen zwei
        /// speichersicheren Setzer, dazu die abgerechnete Kostenzeile.
        /// </summary>
        private void WriteRuleValues(GameBuildingManagerAPI buildings)
        {
            BuildingCost cost = new BuildingCost
            {
                Wood = GeneratedDockRulesContract.WoodCost,
                Stone = 0,
                Iron = 0,
                Pitch = 0,
                Gold = GeneratedDockRulesContract.GoldCost,
            };
            // Drittes Argument woertlich false: mit dem Vorgabewert true
            // schriebe der Unity-Sichtschreiber 20 Byte exakt hinter das Ende
            // von GameData.game_data_txt (int[545]) - siehe Kopf der Datei.
            buildings.SetDefaultCost(
                DockPlacementRule.DockStruct,
                cost,
                updateUnityEngineSite: false);
            buildings.SetDefaultHealth(
                DockPlacementRule.DockStruct,
                GeneratedDockRulesContract.Health);
            WriteLiveCost(buildings, cost);
        }

        /// <summary>
        /// Schreibt die ABGERECHNETE Kostentabelle. Ohne das kostet der Hafen
        /// nichts, obwohl die Vorgabetabelle unsere Werte traegt.
        /// </summary>
        /// <remarks>
        /// Am 15.08.2026 im Spiel gemessen: "Dock default cost after rules:
        /// Wood=20 ... Gold=30" neben "Dock live cost after rules: Wood=0 ...
        /// Gold=0". Die Disassemblierung von CrusaderDE.dll erklaert es: Es gibt
        /// ZWEI native Kostentabellen. Die Vorgabetabelle
        /// (gBuildingCostDefaults) ist nur die Quelle; abgerechnet wird aus
        /// fuenf verschraenkten Spalten im GameBuildingManager, und die werden
        /// GENAU EINMAL JE PROZESS aus der Vorgabe kopiert - hinter einem
        /// "schon erledigt"-Byte, aus DLL_LoadMapToPlay und allen
        /// DLL_PreInitMap_*-Ausfuhren heraus. Wenn unsere Regel laeuft, ist die
        /// Kopie laengst gefallen und faellt nie wieder. SetDefaultCost frueher
        /// aufzurufen hilft deshalb nicht.
        ///
        /// Die fuenf Einzelsetzer des Extenders treffen genau diese Stelle -
        /// aber unbedingt auch den Unity-Spiegel, und dessen Zeiger liegt fuer
        /// Index 109 hinter dem Ende von int[545]. Sie stehen deshalb im Kopf
        /// dieser Datei namentlich unter Verbot; hier faellt derselbe native
        /// Schreibzugriff ohne den Spiegel.
        ///
        /// SCHRANKE. Der Kopf dieser Datei hielt bis zum 15.08.2026 fest, in
        /// diese Tabelle werde "nie geschrieben", weil ihr ein Ende-Symbol
        /// fehlt und ihre Laenge damit ungeprueft sei. Das ist jetzt gemessen
        /// statt angenommen - die Fuellschleife bei RVA 0xC2330 gelesen:
        ///
        ///   lea rax,[rip+0x219e80]   -> 0x2DC1C4, Vorgabetabelle + 4
        ///   lea rbx,[rip+0x21a703]   -> 0x2DCA5C, deren Ende + 4
        ///   add rax,0x14 / cmp rax,rbx / jl
        ///
        /// (0x2DCA5C - 0x2DC1C4) / 0x14 = 2200 / 20 = GENAU 110 Durchlaeufe,
        /// Indizes 0 bis 109. Das Spiel selbst beschreibt Platz 109 bei jedem
        /// Kartenstart; dieser Schreibzugriff geht also nicht weiter als der
        /// native. Wichtiger noch: Die Abbruchmarke der Schleife IST das Ende
        /// der Vorgabetabelle. Beide Tabellen haben damit bauartbedingt
        /// dieselbe Eintragszahl, und die Schranke aus
        /// <see cref="RuleTablesUnreachable" /> - aus
        /// BuildingDefaultCostsTable(End)VA zur Laufzeit gerechnet, im Spiel
        /// gemessen 110 - gilt fuer diese Tabelle mit. Sie laeuft in Apply vor
        /// dem ersten Schreiben.
        ///
        /// Kein <c>unsafe</c>: Marshal reicht, und das haelt die
        /// Baukonfiguration unveraendert.
        /// </remarks>
        private void WriteLiveCost(
            GameBuildingManagerAPI buildings, BuildingCost cost)
        {
            NativeTable table;
            long[] columns;
            string failure = OpenLiveCostTable(out table, out columns);
            if (failure != null)
            {
                _error(failure + "; the live cost table stays untouched.");
                return;
            }
            // Selbstpruefung VOR dem ersten Schreiben, an einem Bauwerk mit ab
            // Werk von null verschiedenen Holzkosten. Sie prueft dreierlei auf
            // einmal: dass das gefundene Modul dasselbe ist wie das des
            // Extenders, dass die Schrittweite stimmt (20 Byte hier, 5 int
            // dort) und dass der Spaltenversatz sitzt.
            if (!table.Verify(
                    (long)(int)eStructs.STRUCT_HOVEL,
                    columns[0],
                    buildings.GetWoodCost(eStructs.STRUCT_HOVEL),
                    out failure))
            {
                _error(failure + "; the live cost table stays untouched.");
                return;
            }
            long dock = (long)(int)DockPlacementRule.DockStruct;
            if (!_originalLiveCaptured)
            {
                _originalLiveCost = new BuildingCost
                {
                    Wood = table.Read(dock, columns[0]),
                    Stone = table.Read(dock, columns[1]),
                    Iron = table.Read(dock, columns[2]),
                    Pitch = table.Read(dock, columns[3]),
                    Gold = table.Read(dock, columns[4]),
                };
                _originalLiveCaptured = true;
                _info(
                    "Dock rules captured live originals: "
                    + _originalLiveCost.ToString());
            }
            WriteRow(table, columns, dock, cost);
        }

        /// <summary>
        /// Die abgerechnete Tabelle aufschliessen und ihre fuenf Spalten
        /// bestimmen; null heisst: bereit.
        /// </summary>
        /// <remarks>
        /// Die Eintragszahl kommt aus der VORGABEtabelle, und das ist kein
        /// Notbehelf, sondern die Bruecke aus der Messung: Die Abbruchmarke der
        /// Fuellschleife bei RVA 0xC2330 IST das Ende der Vorgabetabelle, beide
        /// fassen also bauartbedingt gleich viele Eintraege.
        /// </remarks>
        private static string OpenLiveCostTable(
            out NativeTable table, out long[] columns)
        {
            table = null;
            columns = null;
            GameGlobalsManager globals = GameGlobalsManager.Instance;
            long[] rvas = new long[]
            {
                (long)globals.BuildingWoodCostsTableRVA,
                (long)globals.BuildingStoneCostsTableRVA,
                (long)globals.BuildingIronIngotsCostsTableRVA,
                (long)globals.BuildingRawPitchCostsTableRVA,
                (long)globals.BuildingGoldCostsTableRVA,
            };
            string shape = LiveColumnsMalformed(
                rvas[0], rvas[1], rvas[2], rvas[3], rvas[4]);
            if (shape != null)
            {
                return shape;
            }
            ulong start = globals.BuildingDefaultCostsTableVA;
            ulong end = globals.BuildingDefaultCostsTableEndVA;
            if (start == 0UL || end <= start)
            {
                return "Dock rules: default cost table was not resolved";
            }
            long entries = (long)((end - start) / BuildingCostSize);
            long lowest = rvas[0];
            foreach (long rva in rvas)
            {
                if (rva < lowest)
                {
                    lowest = rva;
                }
            }
            string failure;
            if (!NativeTable.TryOpen(
                    "Dock live cost",
                    (ulong)lowest,
                    (long)BuildingCostSize,
                    entries,
                    out table,
                    out failure))
            {
                return failure;
            }
            columns = new long[rvas.Length];
            for (int index = 0; index < rvas.Length; index++)
            {
                columns[index] = rvas[index] - lowest;
            }
            return null;
        }

        /// <summary>
        /// Schreibt die fuenf Spalten eines Eintrags. Die Schranke liegt in
        /// <see cref="NativeTable" />; ein Fehlschlag wird gemeldet, nie
        /// verschluckt.
        /// </summary>
        private void WriteRow(
            NativeTable table, long[] columns, long building, BuildingCost cost)
        {
            int[] values = new int[]
            {
                cost.Wood, cost.Stone, cost.Iron, cost.Pitch, cost.Gold,
            };
            for (int index = 0; index < values.Length; index++)
            {
                string failure;
                if (!table.TryWrite(building, columns[index], values[index], out failure))
                {
                    _error(failure);
                    return;
                }
            }
        }

        /// <summary>
        /// Prueft die Bauform der fuenf Spalten; null heisst: unauffaellig.
        /// </summary>
        /// <remarks>
        /// Die fuenf Spalten sind keine fuenf Tabellen, sondern fuenf Sichten
        /// auf EINEN Satz von 20-Byte-Eintraegen - in der Fuellschleife an den
        /// fuenf Zielen +0x318FDC, +0xFE0, +0xFE4, +0xFE8, +0xFEC abzulesen,
        /// also fuenf aufeinanderfolgende int. Genau das wird hier
        /// nachgerechnet: fuenf verschiedene Werte, alle innerhalb von 16 Byte
        /// ueber dem kleinsten, jeder auf einer durch vier teilbaren Stufe.
        /// Damit deckt die Selbstpruefung auf der Holzspalte auch die anderen
        /// vier ab, ohne dass ein zweites Bauwerk mit bekannten Kosten in
        /// Stein, Eisen, Pech und Gold noetig waere.
        /// </remarks>
        private static string LiveColumnsMalformed(
            long wood, long stone, long iron, long pitch, long gold)
        {
            long[] columns = new long[] { wood, stone, iron, pitch, gold };
            long lowest = long.MaxValue;
            foreach (long column in columns)
            {
                if (column == 0L)
                {
                    return "Dock rules: a live cost column was not resolved";
                }
                if (column < lowest)
                {
                    lowest = column;
                }
            }
            int seen = 0;
            foreach (long column in columns)
            {
                long offset = column - lowest;
                if (offset % 4L != 0L || offset > 16L)
                {
                    return "Dock rules: the live cost columns are not one"
                        + " interleaved record";
                }
                int bit = 1 << (int)(offset / 4L);
                if ((seen & bit) != 0)
                {
                    return "Dock rules: two live cost columns share an offset";
                }
                seen |= bit;
            }
            return null;
        }

        /// <summary>
        /// Wachposten vor jedem Schreiben; null heisst: alles erreichbar.
        /// </summary>
        private static string RuleTablesUnreachable()
        {
            ulong start = GameGlobalsManager.Instance.BuildingDefaultCostsTableVA;
            ulong end = GameGlobalsManager.Instance.BuildingDefaultCostsTableEndVA;
            if (start == 0UL || end <= start)
            {
                return "Dock rules: default cost table was not resolved";
            }
            long entries = (long)((end - start) / BuildingCostSize);
            if ((long)(int)DockPlacementRule.DockStruct >= entries)
            {
                return "Dock rules: dock index is outside the default cost table"
                    + " (entries=" + entries.ToString(CultureInfo.InvariantCulture)
                    + ")";
            }
            if (GameGlobalsManager.Instance.BuildingHealthTableRVA == 0UL)
            {
                return "Dock rules: building health table was not resolved";
            }
            return null;
        }

        /// <summary>
        /// Die native Vorgabetabelle, mit selbst ausgerechneter Schranke.
        /// </summary>
        /// <remarks>
        /// GetDefaultCost hat keine Bereichspruefung; es rechnet
        /// Anfang - 4 + (int)building * 20 (GameBuildingManagerAPI.cs 1313-1316).
        /// Bliebe der Anfang 0, weil der Muster-Scan des Extenders nicht griff,
        /// waere das ein Lesezugriff auf Adresse 2176 und damit das Ende der
        /// Sitzung. Die Schranke wird deshalb hier aus denselben zwei
        /// oeffentlichen Feldern gebildet, aus denen der Extender seinen
        /// eigenen Zaehler bildet (:267).
        /// </remarks>
        private static string ReadDefaultCost(GameBuildingManagerAPI buildings)
        {
            ulong start = GameGlobalsManager.Instance.BuildingDefaultCostsTableVA;
            ulong end = GameGlobalsManager.Instance.BuildingDefaultCostsTableEndVA;
            if (start == 0UL || end <= start)
            {
                return "unavailable, the default cost table was not resolved";
            }
            long entries = (long)((end - start) / BuildingCostSize);
            long index = (long)(int)DockPlacementRule.DockStruct;
            if (index >= entries)
            {
                return "out of range, entries="
                    + entries.ToString(CultureInfo.InvariantCulture);
            }
            BuildingCost cost = buildings.GetDefaultCost(DockPlacementRule.DockStruct);
            // BuildingCost hat ein eigenes ToString (Wood=.., Stone=.., ...).
            return cost.ToString() + " (entries="
                + entries.ToString(CultureInfo.InvariantCulture) + ")";
        }

        /// <summary>
        /// Die laufende, verschraenkte Kostentabelle.
        /// </summary>
        /// <remarks>
        /// Die fuenf Getter sind fuenf Sichten auf EINE verschraenkte Tabelle:
        /// GetWoodCost &amp; Co. rechnen (int)building * 5 und lesen vier Byte,
        /// also Versatz 109 * 20 = 2180 vom jeweiligen Feld des Eintrags 0
        /// (GameBuildingManagerAPI.cs 1376-1531). Fuer die Vorgabetabelle ist
        /// die Laenge gemessen (2200 Byte = 110 Eintraege); fuer diese laufende
        /// Tabelle gibt es kein Ende-Symbol. Ihre Laenge stand hier bis zum
        /// 15.08.2026 als UNGEPRUEFT, mit dem Schluss, in sie werde nie
        /// geschrieben. Inzwischen ist sie ueber die Fuellschleife bei
        /// RVA 0xC2330 belegt - deren Abbruchmarke ist das Ende der
        /// Vorgabetabelle, beide Tabellen fassen also gleich viele Eintraege.
        /// Die Begruendung steht bei <see cref="WriteLiveCost" />.
        /// </remarks>
        private static string ReadLiveCost(GameBuildingManagerAPI buildings)
        {
            eStructs dock = DockPlacementRule.DockStruct;
            return "Wood=" + buildings.GetWoodCost(dock).ToString(
                    CultureInfo.InvariantCulture)
                + ", Stone=" + buildings.GetStoneCost(dock).ToString(
                    CultureInfo.InvariantCulture)
                + ", Iron=" + buildings.GetIronIngotCost(dock).ToString(
                    CultureInfo.InvariantCulture)
                + ", Pitch=" + buildings.GetRawPitchCost(dock).ToString(
                    CultureInfo.InvariantCulture)
                + ", Gold=" + buildings.GetGoldCost(dock).ToString(
                    CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// Trefferpunkte von 109 und seinen Nachbarn, plus zwei Massstaebe.
        /// </summary>
        /// <remarks>
        /// Die Nachbarn 108 und 110 stehen daneben, weil sie die einzige
        /// Handhabe sind, um Fuellung von einem echten Eintrag zu unterscheiden;
        /// Hovel und Weizenfarm geben die Groessenordnung. Gelesen wird ueber
        /// den ManagedNativeArray des Extenders, der auf 237 Eintraege gefasst
        /// ist (:262) - Index 109 liegt weit darin.
        /// </remarks>
        private static string ReadDefaultHealth(GameBuildingManagerAPI buildings)
        {
            return "108=" + buildings.GetDefaultHealth((eStructs)108).ToString(
                    CultureInfo.InvariantCulture)
                + " dock(109)=" + buildings.GetDefaultHealth(
                    DockPlacementRule.DockStruct).ToString(
                    CultureInfo.InvariantCulture)
                + " 110=" + buildings.GetDefaultHealth((eStructs)110).ToString(
                    CultureInfo.InvariantCulture)
                + " hovel=" + buildings.GetDefaultHealth(
                    eStructs.STRUCT_HOVEL).ToString(CultureInfo.InvariantCulture)
                + " wheatfarm=" + buildings.GetDefaultHealth(
                    eStructs.STRUCT_WHEATFARM).ToString(
                    CultureInfo.InvariantCulture);
        }

        private void FailClosed(Exception exception)
        {
            if (_failed)
            {
                return;
            }
            _failed = true;
            _pendingSampleValid = false;
            _pendingSample = null;
            _error(
                "Dock placement lane failed closed and stopped: "
                + exception);
            // Nach der Fehlermeldung, damit die Ursache im Protokoll vor den
            // Restore-Zeilen steht. Restore selbst meldet nur, wirft nie.
            Restore("fail closed");
        }
    }
}
