#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using SHCDESE.API;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Phase 0 des Waffenstillstands-Ausbaus: die fuenf offenen Fragen im
    /// laufenden Spiel beantworten, bevor der Entwurf darauf gebaut wird.
    /// </summary>
    /// <remarks>
    /// Gemessen werden soll (Auftrag vom 07.09.2026):
    /// <list type="number">
    /// <item>Welches Raster beschreibt "Territorium" brauchbar - der
    /// Mauerbesitz (<c>GetTilePlayerOwnerId</c>, seit 1.39) oder die
    /// KI-Bauanspruchsmaske (<c>GetAIVBlockData</c>, erst ab SE 1.45)?</item>
    /// <item>Bleibt eine geschriebene <c>TribeStance</c> stehen, oder
    /// ueberschreibt die native KI sie?</item>
    /// <item>Wirkt <c>AttackNearestUnit=false</c>, oder wird es
    /// zurueckgesetzt?</item>
    /// <item>Wie schnell erfasst ein Stamm nach dem Loeschen seines Ziels
    /// ein neues?</item>
    /// <item>Nimmt die KI einen UMGELENKTEN Marschbefehl an, oder wiederholt
    /// sie ihn? (Heute weisen wir ab; Umlenken waere "aus dem Weg gehen".)
    /// </item>
    /// </list>
    ///
    /// Die Sonde schreibt in nativen Zustand - anders sind 2 bis 5 nicht zu
    /// beantworten. Deshalb gilt hier dieselbe Strenge wie beim Teamwechsel:
    /// <list type="bullet">
    /// <item>ein Versuch zur Zeit, ein Stamm zur Zeit, festes Fenster;</item>
    /// <item>jeder Schreibvorgang steht vorher im Journal
    /// (<see cref="V2ProbeSubject"/>) und wird daraus exakt
    /// zurueckgenommen;</item>
    /// <item>Ruecknahme auch bei Vertragsende, Kartenabbau, Abschaltung und
    /// Plugin-Ruecknahme - kein Stamm bleibt befriedet zurueck;</item>
    /// <item>die Sonde wirft nie; ein Fehler schaltet sie ab, nicht die
    /// Karte.</item>
    /// </list>
    ///
    /// Nach einem Durchlauf je Karte schaltet sie sich selbst ab
    /// (<see cref="V2ProbeStage.Done"/>).
    /// </remarks>
    internal sealed partial class DiplomacyFeature
    {
        private enum V2ProbeStage
        {
            Idle = 0,
            Territory = 1,
            StanceHold = 2,
            NoAutoTarget = 3,
            ClearTarget = 4,
            RedirectMove = 5,
            Done = 6,
        }

        /// <summary>Was an einem Stamm veraendert wurde - die Rueckgabe.</summary>
        private sealed class V2ProbeSubject
        {
            internal int TribeId;
            internal int Owner;
            internal bool StanceWritten;
            internal TribeStance OriginalStance;
            internal bool AttackNearestWritten;
            internal bool OriginalAttackNearest;
            internal bool TargetCleared;
            internal ushort OriginalTargetUnitId;
            internal uint OriginalTargetOwner;
        }

        // Ein Versuch laeuft 192 Takte (rund sechs Sekunden bei der nativen
        // Taktrate) und wird bei 1, 2, 4, 8, 16, 32, 64, 128, 192 abgelesen.
        private const int V2ProbeWindowTicks = 192;
        private static readonly int[] V2ProbeSampleOffsets =
        {
            1, 2, 4, 8, 16, 32, 64, 128, 192,
        };
        private const int V2ProbeCooldownTicks = 64;
        private const int V2ProbeMaxLogLines = 120;

        private V2ProbeStage _v2ProbeStage = V2ProbeStage.Idle;
        private V2ProbeStage _v2ProbePendingStage = V2ProbeStage.Territory;
        private V2ProbeSubject _v2ProbeSubject;
        private long _v2ProbeStartedTick = long.MinValue;
        private long _v2ProbeNextStageTick = long.MinValue;
        private int _v2ProbeSampleIndex;
        private int _v2ProbeLogLines;
        private bool _v2ProbeDegraded;
        private bool _v2ProbeTerritoryLogged;
        // Wie oft die laufende Stufe nicht anwendbar war. Nach drei Versuchen
        // wird sie uebersprungen - ein Versuchsplan, der nicht endet, ist
        // keiner (07.09.2026: 96 Versuche an no_auto_target am selben Stamm).
        private int _v2ProbeStageAttempts;
        private const int V2ProbeMaxStageAttempts = 3;
        private string _v2ProbeSeries;
        // Umlenkversuch: was der Marschbefehlshaken beobachtet hat.
        private int _v2ProbeMoveOrdersSeen;
        private int _v2ProbeMoveRedirected;
        private int _v2ProbeMoveRepeated;
        private readonly Dictionary<int, long> _v2ProbeMoveLastTick =
            new Dictionary<int, long>();

        /// <summary>
        /// Schalter der Phase-0-Sonde.
        /// </summary>
        /// <remarks>
        /// Am 07.09.2026 abgeschaltet. Die Gebietsvermessung (Frage 1, rein
        /// lesend) hat geliefert: der KI-Bauanspruch gibt je Spieler eine
        /// zusammenhaengende Flaeche (724 bis 2220 Kacheln), der Mauerbesitz
        /// dagegen 0 bis 982 mit ausgefransten Grenzen - ein Spieler hatte
        /// gar keine. Fuer "Territorium" taugt also der AIV-Anspruch.
        ///
        /// Am Vormittag des 07.09.2026 abgeschaltet, weil der Absturz
        /// unmittelbar auf ihren ersten Schreibvorgang (stance_hold) folgte
        /// und die Startzeile fehlte - sie stand hinter dem Schreibvorgang.
        ///
        /// **Am Nachmittag des 07.09.2026 wieder eingeschaltet**, auf
        /// ausdruecklichen Auftrag des Benutzers und mit widerlegter
        /// Verdachtslage:
        /// <list type="bullet">
        /// <item>Die Absturzursache liegt im Extender - der gemeinsame Stub
        /// aller 76 Kontexthaken rechnet den Stapel seit 2.0.0 nicht mehr
        /// exakt zurueck. Nachgewiesen mit NUR dem Extender im Pluginordner,
        /// ohne jeden Fremdmod.</item>
        /// <item>Der Extender laeuft jetzt auf 1.45.0, wo das nicht
        /// auftritt; ein Lauf ueber siebzehn Minuten blieb stabil.</item>
        /// <item>Die Sonde lief damals im Simulationstakt, also im rohen
        /// Kontexthaken. Heute laeuft sie im Unity-Bild.</item>
        /// <item>Die Startzeile steht jetzt VOR dem Schreibvorgang
        /// (`status=about_to_write`).</item>
        /// </list>
        ///
        /// Sie beantwortet die offene Frage zu den Kampfanimationen unter
        /// Waffenruhe: welcher Schreibzugriff haelt die KI wirklich ab, und
        /// haelt er.
        /// </remarks>
        // Production audit 2026-09-07: this experiment rewrites native tribe
        // state and must not run automatically in ordinary treaty gameplay.
        // The read-only runtime counters remain available independently.
        private const bool V2ProbeEnabled = false;

        private bool V2ProbeRedirectActive
        {
            get
            {
                return _v2ProbeStage == V2ProbeStage.RedirectMove
                    && !_v2ProbeDegraded;
            }
        }

        /// <summary>
        /// Je Takt. Tut nichts, solange kein Versuch laeuft; startet den
        /// naechsten erst, wenn ein Pakt steht und der vorige zurueckgenommen
        /// ist.
        /// </summary>
        private void TickV2Probe()
        {
            if (!V2ProbeEnabled
                || _v2ProbePendingStage == V2ProbeStage.Done
                || _v2ProbeDegraded)
            {
                return;
            }
            try
            {
                if (!V2StandoffEnforceable())
                {
                    // Ohne laufenden Pakt gibt es keinen Vertragspartner, an
                    // dem sich etwas messen liesse. Angefangenes zurueckgeben
                    // und den Versuch spaeter neu beginnen.
                    if (_v2ProbeStage != V2ProbeStage.Idle)
                    {
                        RestoreV2ProbeSubject("no_treaty");
                        _v2ProbeStage = V2ProbeStage.Idle;
                        _v2ProbeNextStageTick =
                            ReadSimulationTick() + V2ProbeCooldownTicks;
                    }
                    return;
                }
                if (_v2ProbeStage == V2ProbeStage.Idle)
                {
                    if (ReadSimulationTick() < _v2ProbeNextStageTick)
                    {
                        return;
                    }
                    BeginV2ProbeStage(_v2ProbePendingStage);
                    return;
                }
                if (_v2ProbeStage == V2ProbeStage.Territory)
                {
                    // Rein lesend, in einem Zug erledigt.
                    ProbeV2Territory();
                    FinishV2ProbeStage();
                    return;
                }
                SampleV2ProbeStage();
            }
            catch (Exception exception)
            {
                DegradeV2Probe("tick", exception);
            }
        }

        private void BeginV2ProbeStage(V2ProbeStage stage)
        {
            _v2ProbeStage = stage;
            _v2ProbeStartedTick = ReadSimulationTick();
            _v2ProbeSampleIndex = 0;
            _v2ProbeSeries = null;
            if (stage == V2ProbeStage.Territory)
            {
                return;
            }
            if (stage == V2ProbeStage.RedirectMove)
            {
                _v2ProbeMoveOrdersSeen = 0;
                _v2ProbeMoveRedirected = 0;
                _v2ProbeMoveRepeated = 0;
                _v2ProbeMoveLastTick.Clear();
                LogV2Probe("stage=redirect_move|status=started");
                return;
            }
            V2ProbeSubject subject = SelectV2ProbeSubject();
            if (subject == null)
            {
                // Kein geeigneter Stamm gerade - spaeter erneut versuchen,
                // ohne den Versuchsplan zu verbrauchen.
                _v2ProbeStage = V2ProbeStage.Idle;
                _v2ProbeNextStageTick = ReadSimulationTick() + V2ProbeCooldownTicks;
                return;
            }
            _v2ProbeSubject = subject;
            _v2ProbeStageAttempts++;
            // Diese Zeile steht VOR dem Schreibvorgang. Stirbt das Spiel
            // darin, benennt das Protokoll trotzdem die Stufe und den Stamm -
            // beim Versuch am Vormittag des 07.09.2026 fehlte genau das, weil
            // die Startzeile dahinter stand. Nur beim ERSTEN Versuch je Stufe:
            // sie ist eine Absturzmarke, keine Dauermeldung.
            if (_v2ProbeStageAttempts == 1)
            {
                LogV2Probe("stage=" + V2ProbeStageName(stage)
                    + "|status=about_to_write|tribe="
                    + subject.TribeId.ToString(CultureInfo.InvariantCulture)
                    + "|owner="
                    + subject.Owner.ToString(CultureInfo.InvariantCulture));
            }
            if (!ApplyV2ProbeWrite(stage, subject))
            {
                RestoreV2ProbeSubject("write_failed");
                if (_v2ProbeStageAttempts >= V2ProbeMaxStageAttempts)
                {
                    // Dreimal nicht anwendbar - das ist ein Ergebnis, kein
                    // Grund zum Weiterversuchen. Der Zustand, den diese Stufe
                    // aendern wollte, liegt offenbar gar nicht vor.
                    LogV2Probe("stage=" + V2ProbeStageName(stage)
                        + "|status=skipped|reason=not_applicable|attempts="
                        + _v2ProbeStageAttempts.ToString(
                            CultureInfo.InvariantCulture));
                    _v2ProbePendingStage = NextV2ProbeStage(stage);
                    if (_v2ProbePendingStage == V2ProbeStage.Done)
                    {
                        LogV2Probe("stage=all|status=complete");
                    }
                    _v2ProbeStageAttempts = 0;
                }
                _v2ProbeStage = V2ProbeStage.Idle;
                _v2ProbeNextStageTick = ReadSimulationTick() + V2ProbeCooldownTicks;
                return;
            }
            _v2ProbeStageAttempts = 0;
            LogV2Probe("stage=" + V2ProbeStageName(stage)
                + "|status=started|tribe="
                + subject.TribeId.ToString(CultureInfo.InvariantCulture)
                + "|owner="
                + subject.Owner.ToString(CultureInfo.InvariantCulture)
                + "|stance=" + subject.OriginalStance
                + "|attack_nearest=" + BoolText(subject.OriginalAttackNearest)
                + "|target_unit="
                + subject.OriginalTargetUnitId.ToString(CultureInfo.InvariantCulture)
                + "|target_owner="
                + subject.OriginalTargetOwner.ToString(CultureInfo.InvariantCulture));
        }

        /// <summary>Der eigentliche Schreibvorgang, nach dem Journal.</summary>
        private unsafe bool ApplyV2ProbeWrite(
            V2ProbeStage stage,
            V2ProbeSubject subject)
        {
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            if (tribes == null || !tribes.IsValidId(subject.TribeId))
            {
                return false;
            }
            switch (stage)
            {
                case V2ProbeStage.StanceHold:
                    if (subject.OriginalStance == TribeStance.Hold)
                    {
                        // Ohne Aenderung misst der Versuch nichts.
                        return false;
                    }
                    if (!tribes.SetStance(subject.TribeId, TribeStance.Hold))
                    {
                        return false;
                    }
                    subject.StanceWritten = true;
                    return true;
                case V2ProbeStage.NoAutoTarget:
                    if (!subject.OriginalAttackNearest)
                    {
                        return false;
                    }
                    if (!tribes.SetAttackNearestUnit(subject.TribeId, false))
                    {
                        return false;
                    }
                    subject.AttackNearestWritten = true;
                    return true;
                case V2ProbeStage.ClearTarget:
                    if (subject.OriginalTargetUnitId == 0
                        && subject.OriginalTargetOwner == 0)
                    {
                        return false;
                    }
                    GameTribe* tribe;
                    if (!tribes.TryGetTribeById(subject.TribeId, out tribe)
                        || tribe == null)
                    {
                        return false;
                    }
                    tribe->r_AttackTargetUnitId = 0;
                    tribe->r_AttackTargetOwnerPlayerId = 0u;
                    subject.TargetCleared = true;
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>
        /// Liest den geschriebenen Wert an den geplanten Stellen zurueck und
        /// haengt ihn an die Messreihe. Am Fensterende: zurueckgeben.
        /// </summary>
        private unsafe void SampleV2ProbeStage()
        {
            long elapsed = ReadSimulationTick() - _v2ProbeStartedTick;
            if (_v2ProbeStage == V2ProbeStage.RedirectMove)
            {
                // Dieser Versuch hat keinen einzelnen Stamm als Gegenstand -
                // er zaehlt, was der Marschbefehlshaken im Fenster sieht.
                if (elapsed >= V2ProbeWindowTicks)
                {
                    FinishV2ProbeStage();
                }
                return;
            }
            V2ProbeSubject subject = _v2ProbeSubject;
            if (subject == null)
            {
                FinishV2ProbeStage();
                return;
            }
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            if (tribes == null || !tribes.IsValidId(subject.TribeId))
            {
                // Der Stamm ist gefallen oder aufgeloest - nichts mehr
                // zurueckzunehmen, aber die Reihe endet hier.
                AppendV2ProbeSample(elapsed, "gone");
                subject.StanceWritten = false;
                subject.AttackNearestWritten = false;
                subject.TargetCleared = false;
                FinishV2ProbeStage();
                return;
            }
            while (_v2ProbeSampleIndex < V2ProbeSampleOffsets.Length
                && elapsed >= V2ProbeSampleOffsets[_v2ProbeSampleIndex])
            {
                int offset = V2ProbeSampleOffsets[_v2ProbeSampleIndex];
                _v2ProbeSampleIndex++;
                string value;
                switch (_v2ProbeStage)
                {
                    case V2ProbeStage.StanceHold:
                        value = tribes.GetStance(subject.TribeId).ToString();
                        break;
                    case V2ProbeStage.NoAutoTarget:
                        value = BoolText(
                            tribes.GetAttackNearestUnit(subject.TribeId));
                        break;
                    case V2ProbeStage.ClearTarget:
                        GameTribe* tribe;
                        if (tribes.TryGetTribeById(subject.TribeId, out tribe)
                            && tribe != null)
                        {
                            value = tribe->r_AttackTargetUnitId
                                    .ToString(CultureInfo.InvariantCulture)
                                + "/"
                                + tribe->r_AttackTargetOwnerPlayerId
                                    .ToString(CultureInfo.InvariantCulture);
                        }
                        else
                        {
                            value = "gone";
                        }
                        break;
                    default:
                        value = "?";
                        break;
                }
                AppendV2ProbeSample(offset, value);
            }
            if (elapsed >= V2ProbeWindowTicks)
            {
                FinishV2ProbeStage();
            }
        }

        private void AppendV2ProbeSample(long offset, string value)
        {
            string entry = offset.ToString(CultureInfo.InvariantCulture)
                + ":" + value;
            _v2ProbeSeries = string.IsNullOrEmpty(_v2ProbeSeries)
                ? entry
                : _v2ProbeSeries + "," + entry;
        }

        /// <summary>Versuch beenden: Ergebnis melden, zurueckgeben, weiter.</summary>
        private void FinishV2ProbeStage()
        {
            V2ProbeStage stage = _v2ProbeStage;
            if (stage == V2ProbeStage.RedirectMove)
            {
                LogV2Probe("stage=redirect_move|status=done|orders="
                    + _v2ProbeMoveOrdersSeen.ToString(CultureInfo.InvariantCulture)
                    + "|redirected="
                    + _v2ProbeMoveRedirected.ToString(CultureInfo.InvariantCulture)
                    + "|repeated="
                    + _v2ProbeMoveRepeated.ToString(CultureInfo.InvariantCulture));
            }
            else if (stage != V2ProbeStage.Territory && _v2ProbeSubject != null)
            {
                LogV2Probe("stage=" + V2ProbeStageName(stage)
                    + "|status=done|tribe="
                    + _v2ProbeSubject.TribeId.ToString(CultureInfo.InvariantCulture)
                    + "|series=" + (_v2ProbeSeries ?? "none"));
            }
            RestoreV2ProbeSubject("window_end");
            _v2ProbeSeries = null;
            // Der naechste Versuch beginnt erst nach der Abkuehlzeit; bis
            // dahin ist an keinem Stamm etwas geschrieben.
            _v2ProbePendingStage = NextV2ProbeStage(stage);
            _v2ProbeStage = V2ProbeStage.Idle;
            _v2ProbeNextStageTick = ReadSimulationTick() + V2ProbeCooldownTicks;
            if (_v2ProbePendingStage == V2ProbeStage.Done)
            {
                LogV2Probe("stage=all|status=complete");
            }
        }

        private static V2ProbeStage NextV2ProbeStage(V2ProbeStage stage)
        {
            switch (stage)
            {
                case V2ProbeStage.Territory:
                    return V2ProbeStage.StanceHold;
                case V2ProbeStage.StanceHold:
                    return V2ProbeStage.NoAutoTarget;
                case V2ProbeStage.NoAutoTarget:
                    return V2ProbeStage.ClearTarget;
                case V2ProbeStage.ClearTarget:
                    return V2ProbeStage.RedirectMove;
                default:
                    return V2ProbeStage.Done;
            }
        }

        private static string V2ProbeStageName(V2ProbeStage stage)
        {
            switch (stage)
            {
                case V2ProbeStage.Territory: return "territory";
                case V2ProbeStage.StanceHold: return "stance_hold";
                case V2ProbeStage.NoAutoTarget: return "no_auto_target";
                case V2ProbeStage.ClearTarget: return "clear_target";
                case V2ProbeStage.RedirectMove: return "redirect_move";
                case V2ProbeStage.Done: return "done";
                default: return "idle";
            }
        }

        /// <summary>
        /// Nimmt jeden Schreibvorgang exakt zurueck. Wird auch bei
        /// Vertragsende, Kartenabbau und Abschaltung gerufen - deshalb muss
        /// sie mehrfach aufrufbar und ohne laufenden Versuch harmlos sein.
        /// </summary>
        private unsafe void RestoreV2ProbeSubject(string reason)
        {
            V2ProbeSubject subject = _v2ProbeSubject;
            _v2ProbeSubject = null;
            if (subject == null)
            {
                return;
            }
            int restored = 0;
            try
            {
                GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
                if (tribes != null && tribes.IsValidId(subject.TribeId))
                {
                    if (subject.StanceWritten
                        && tribes.SetStance(
                            subject.TribeId,
                            subject.OriginalStance))
                    {
                        restored++;
                    }
                    if (subject.AttackNearestWritten
                        && tribes.SetAttackNearestUnit(
                            subject.TribeId,
                            subject.OriginalAttackNearest))
                    {
                        restored++;
                    }
                    if (subject.TargetCleared)
                    {
                        GameTribe* tribe;
                        if (tribes.TryGetTribeById(subject.TribeId, out tribe)
                            && tribe != null)
                        {
                            // Nur zuruecksetzen, wenn die KI in der
                            // Zwischenzeit nichts Eigenes eingetragen hat -
                            // ein neues Ziel ist ihr Zustand, nicht unserer.
                            if (tribe->r_AttackTargetUnitId == 0
                                && tribe->r_AttackTargetOwnerPlayerId == 0u)
                            {
                                tribe->r_AttackTargetUnitId =
                                    subject.OriginalTargetUnitId;
                                tribe->r_AttackTargetOwnerPlayerId =
                                    subject.OriginalTargetOwner;
                            }
                            restored++;
                        }
                    }
                }
                bool wroteAnything = subject.StanceWritten
                    || subject.AttackNearestWritten
                    || subject.TargetCleared;
                if (wroteAnything)
                {
                    LogV2Probe("stage=restore|tribe="
                        + subject.TribeId.ToString(CultureInfo.InvariantCulture)
                        + "|restored="
                        + restored.ToString(CultureInfo.InvariantCulture)
                        + "|reason=" + Safe(reason));
                }
            }
            catch (Exception exception)
            {
                DegradeV2Probe("restore", exception);
            }
        }

        /// <summary>
        /// Ein Stamm des Vertragspartners mit Kampffuehrer. Bevorzugt einer,
        /// der in der Zone des Spielerblocks steht - dort entscheidet sich,
        /// ob das Abstandsgebot spaeter greift.
        /// </summary>
        private unsafe V2ProbeSubject SelectV2ProbeSubject()
        {
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (tribes == null || units == null)
            {
                return null;
            }
            var tribeIds = new List<int>();
            tribes.GetAllTribes(tribeIds, AliveState.IsAlive);
            tribeIds.Sort();
            V2ProbeSubject fallback = null;
            foreach (int tribeId in tribeIds)
            {
                int owner = TribeOwner(tribeId);
                bool localBloc;
                if (owner <= 0
                    || !V2TryGetTreatySide(owner, out localBloc)
                    || localBloc)
                {
                    continue;
                }
                int leader = tribes.GetLeaderUnitId(tribeId);
                if (leader <= 0
                    || !units.IsValidId(leader)
                    || !IsCombatUnit(units.GetType(leader)))
                {
                    continue;
                }
                GameTribe* tribe;
                if (!tribes.TryGetTribeById(tribeId, out tribe) || tribe == null)
                {
                    continue;
                }
                var candidate = new V2ProbeSubject
                {
                    TribeId = tribeId,
                    Owner = owner,
                    OriginalStance = tribes.GetStance(tribeId),
                    OriginalAttackNearest = tribes.GetAttackNearestUnit(tribeId),
                    OriginalTargetUnitId = tribe->r_AttackTargetUnitId,
                    OriginalTargetOwner = tribe->r_AttackTargetOwnerPlayerId,
                };
                UnmanagedVector2<ushort> position =
                    units.GetCurrentWorldTilePosition(leader);
                if (V2FindOpposingTreatyZone(localBloc, position.X, position.Y)
                    != null)
                {
                    return candidate;
                }
                if (fallback == null)
                {
                    fallback = candidate;
                }
            }
            return fallback;
        }

        /// <summary>
        /// Frage 1, rein lesend: welches Raster beschreibt Territorium? Es
        /// wird jede zweite Kachel abgetastet - fuer Deckungsgrad und
        /// Ausdehnung genau genug, und ein Viertel der Arbeit.
        /// </summary>
        private void ProbeV2Territory()
        {
            if (_v2ProbeTerritoryLogged)
            {
                return;
            }
            _v2ProbeTerritoryLogged = true;
            GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
            int mapSize = GameMap.tilemapSize;
            if (tiles == null || mapSize <= 0)
            {
                LogV2Probe("stage=territory|status=unavailable");
                return;
            }
            bool aivAvailable = V2ProbeAivReady();
            var wallCounts = new Dictionary<int, int>();
            var aivCounts = new Dictionary<int, int>();
            var wallBounds = new Dictionary<int, int[]>();
            int sampled = 0;
            for (int tileY = 0; tileY < mapSize; tileY += 2)
            {
                for (int tileX = 0; tileX < mapSize; tileX += 2)
                {
                    int tileId = tiles.GetTileId(tileX, tileY);
                    if (tileId < 0)
                    {
                        continue;
                    }
                    sampled++;
                    int wallOwner = tiles.GetTilePlayerOwnerId(tileId);
                    if (wallOwner > 0 && wallOwner <= 8)
                    {
                        int previous;
                        wallCounts.TryGetValue(wallOwner, out previous);
                        wallCounts[wallOwner] = previous + 1;
                        int[] box;
                        if (!wallBounds.TryGetValue(wallOwner, out box))
                        {
                            box = new[] { tileX, tileY, tileX, tileY };
                            wallBounds[wallOwner] = box;
                        }
                        box[0] = Math.Min(box[0], tileX);
                        box[1] = Math.Min(box[1], tileY);
                        box[2] = Math.Max(box[2], tileX);
                        box[3] = Math.Max(box[3], tileY);
                    }
                    if (!aivAvailable)
                    {
                        continue;
                    }
                    int mask = V2ProbeAivMask(tileId);
                    for (int player = 0; player < 8; player++)
                    {
                        if ((mask & (1 << player)) == 0)
                        {
                            continue;
                        }
                        int previous;
                        aivCounts.TryGetValue(player, out previous);
                        aivCounts[player] = previous + 1;
                    }
                }
            }
            LogV2Probe("stage=territory|status=scanned|map="
                + mapSize.ToString(CultureInfo.InvariantCulture)
                + "|sampled=" + sampled.ToString(CultureInfo.InvariantCulture)
                + "|aiv_api=" + BoolText(aivAvailable));
            foreach (int player in _roster.OrderBy(value => value))
            {
                int wall;
                wallCounts.TryGetValue(player, out wall);
                int aiv;
                aivCounts.TryGetValue(player, out aiv);
                int[] box;
                string bounds = wallBounds.TryGetValue(player, out box)
                    ? box[0].ToString(CultureInfo.InvariantCulture) + ","
                        + box[1].ToString(CultureInfo.InvariantCulture) + ".."
                        + box[2].ToString(CultureInfo.InvariantCulture) + ","
                        + box[3].ToString(CultureInfo.InvariantCulture)
                    : "none";
                LogV2Probe("stage=territory|player="
                    + player.ToString(CultureInfo.InvariantCulture)
                    + "|wall_tiles=" + wall.ToString(CultureInfo.InvariantCulture)
                    + "|wall_bounds=" + bounds
                    + "|aiv_tiles=" + aiv.ToString(CultureInfo.InvariantCulture)
                    + "|alive=" + BoolText(IsAlivePlayer(player)));
            }
        }

        // GetAIVBlockData gibt es erst ab SE 1.45. Die Diplomatie laeuft ab
        // 1.39 - deshalb ueber Reflexion, und ohne den Zugang faellt nur
        // dieser Teil der Messung aus.
        private static bool _v2ProbeAivResolved;
        private static MethodInfo _v2ProbeAivMethod;

        private bool V2ProbeAivReady()
        {
            if (!_v2ProbeAivResolved)
            {
                _v2ProbeAivResolved = true;
                try
                {
                    _v2ProbeAivMethod = typeof(GameTileManagerAPI).GetMethod(
                        "GetAIVBlockData",
                        BindingFlags.Public | BindingFlags.Instance,
                        null,
                        new[] { typeof(int) },
                        null);
                }
                catch (Exception)
                {
                    _v2ProbeAivMethod = null;
                }
            }
            return _v2ProbeAivMethod != null;
        }

        private int V2ProbeAivMask(int tileId)
        {
            try
            {
                object value = _v2ProbeAivMethod.Invoke(
                    GameTileManagerAPI.Instance,
                    new object[] { tileId });
                return value == null
                    ? 0
                    : Convert.ToInt32(
                        Convert.ChangeType(
                            value,
                            Enum.GetUnderlyingType(value.GetType()),
                            CultureInfo.InvariantCulture),
                        CultureInfo.InvariantCulture);
            }
            catch (Exception)
            {
                return 0;
            }
        }

        /// <summary>
        /// Frage 5: Der Marschbefehlshaken meldet der Sonde, was er sieht.
        /// Waehrend des Umlenkversuchs wird der Befehl nicht abgewiesen,
        /// sondern auf einen Punkt ausserhalb der Zone umgeschrieben.
        /// </summary>
        private bool V2ProbeRedirectMoveOrder(
            TribeIssueOrderMoveHereEventArgs e,
            V2TreatyZone zone,
            bool localBloc)
        {
            if (!V2ProbeEnabled || !V2ProbeRedirectActive)
            {
                return false;
            }
            try
            {
                _v2ProbeMoveOrdersSeen++;
                long lastTick;
                if (_v2ProbeMoveLastTick.TryGetValue(e.TribeId, out lastTick)
                    && ReadSimulationTick() - lastTick <= V2ProbeWindowTicks)
                {
                    _v2ProbeMoveRepeated++;
                }
                _v2ProbeMoveLastTick[e.TribeId] = ReadSimulationTick();

                int scale = DiplomacyV2CombatRules.WorldPositionsPerLocalTile;
                int radius = DiplomacyV2CombatRules.IntimateZoneRadiusLocalTiles;
                int centerX = zone.X / scale;
                int centerY = zone.Y / scale;
                int deltaX = e.TileX - centerX;
                int deltaY = e.TileY - centerY;
                if (deltaX == 0 && deltaY == 0)
                {
                    deltaX = 1;
                }
                // Auf den Zonenrand hinausschieben, Richtung beibehalten -
                // der Stamm bekommt ein erreichbares Ziel statt einer Absage.
                double length = Math.Sqrt(
                    (double)deltaX * deltaX + (double)deltaY * deltaY);
                double factor = (radius + 3) / Math.Max(1.0, length);
                int targetX = centerX + (int)Math.Round(deltaX * factor);
                int targetY = centerY + (int)Math.Round(deltaY * factor);
                // Native tile coordinates occupy the fixed 800-grid diamond,
                // including on small maps. Never clamp to the map's width.
                if (!GameTileManagerAPI.Instance.IsTileInsideMapBounds(targetX, targetY))
                    return false;
                if (V2FindOpposingTreatyZone(
                        localBloc,
                        DiplomacyV2CombatRules.TileCenterWorld(targetX),
                        DiplomacyV2CombatRules.TileCenterWorld(targetY))
                    != null)
                {
                    // Der Rand liegt selbst noch in einer Zone - dann bleibt
                    // es bei der Absage des Abstandsgebots.
                    return false;
                }
                if (_v2ProbeLogLines < V2ProbeMaxLogLines)
                {
                    LogV2Probe("stage=redirect_move|tribe="
                        + e.TribeId.ToString(CultureInfo.InvariantCulture)
                        + "|from=" + e.TileX.ToString(CultureInfo.InvariantCulture)
                        + "," + e.TileY.ToString(CultureInfo.InvariantCulture)
                        + "|to=" + targetX.ToString(CultureInfo.InvariantCulture)
                        + "," + targetY.ToString(CultureInfo.InvariantCulture));
                }
                e.TileX = targetX;
                e.TileY = targetY;
                _v2ProbeMoveRedirected++;
                return true;
            }
            catch (Exception exception)
            {
                DegradeV2Probe("redirect", exception);
                return false;
            }
        }

        private void LogV2Probe(string fields)
        {
            if (_v2ProbeLogLines >= V2ProbeMaxLogLines)
            {
                return;
            }
            _v2ProbeLogLines++;
            Log("treaty_probe", fields);
        }

        private void DegradeV2Probe(string stage, Exception exception)
        {
            _v2ProbeDegraded = true;
            try
            {
                RestoreV2ProbeSubject("degraded");
            }
            catch (Exception)
            {
                // Die Ruecknahme selbst darf nichts weiterreichen.
            }
            _v2ProbeStage = V2ProbeStage.Done;
            Log("treaty_probe", "stage=" + Safe(stage) + "|status=degraded|reason="
                + Safe(exception.GetType().Name + ":" + exception.Message));
        }

        /// <summary>Kartenwechsel: alles zurueck und von vorn.</summary>
        private void ResetV2ProbeState()
        {
            RestoreV2ProbeSubject("map_reset");
            _v2ProbeStage = V2ProbeStage.Idle;
            _v2ProbePendingStage = V2ProbeStage.Territory;
            _v2ProbeStartedTick = long.MinValue;
            _v2ProbeNextStageTick = long.MinValue;
            _v2ProbeSampleIndex = 0;
            _v2ProbeLogLines = 0;
            _v2ProbeDegraded = false;
            _v2ProbeTerritoryLogged = false;
            _v2ProbeSeries = null;
            _v2ProbeMoveOrdersSeen = 0;
            _v2ProbeMoveRedirected = 0;
            _v2ProbeMoveRepeated = 0;
            _v2ProbeMoveLastTick.Clear();
        }
    }
}
#endif
